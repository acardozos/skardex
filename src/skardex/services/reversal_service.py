"""Reversing a movement (spec 009): the only module that knows what a
Reverso is. The link itself is generic (`Movement.reverses_id`, "this
movement offsets that one"); what may offset what is `REVERSAL_RULES`."""

import enum
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Query, Session

from skardex.constants import COUNT_ADJUSTMENT_REASON, REVERSAL_REASON, SALE_REASON
from skardex.models import Movement, MovementType, User, UserRole
from skardex.services.kardex_service import parse_quantity, register_movement

# Which movement type reverses which: {reversal type: reversed type}. The
# one place that says "an entrada reverses a salida" (EARS-G-03); the
# Bodega/Mostrador Traslado will add its rule here.
REVERSAL_RULES: dict[MovementType, MovementType] = {
    MovementType.ENTRADA: MovementType.SALIDA,
    MovementType.SALIDA: MovementType.ENTRADA,
}

# A chain rooted in one of these is money or the admin's own count: only the
# admin reverses anything in it (EARS-H1-11, H1-15).
_ADMIN_ONLY_ROOT_REASONS = (SALE_REASON, COUNT_ADJUSTMENT_REASON)


class ReversalBlock(enum.StrEnum):
    """Why a movement cannot be reversed right now."""

    SECOND_LEVEL = "second_level"  # a reversal of a reversal
    NOT_ALLOWED = "not_allowed"  # the user's role
    PAID_SALE = "paid_sale"  # undo the sale's payment first
    INACTIVE = "inactive"  # the item is inactive
    NOTHING_PENDING = "nothing_pending"  # already fully reversed


class MovementNotFoundError(Exception):
    """Raised when the movement to reverse does not exist."""


class NoReversalRuleError(Exception):
    """Raised when no rule says what reverses a movement of this type."""


class ReversalBlockedError(Exception):
    """Raised when the movement's state or the user's role forbids it."""

    def __init__(self, block: ReversalBlock) -> None:
        super().__init__(block)
        self.block = block


class ReversalQuantityError(Exception):
    """Raised when the quantity is more than what is left to reverse."""

    def __init__(self, pending: Decimal) -> None:
        super().__init__(pending)
        self.pending = pending


class ReversalDateError(Exception):
    """Raised when the reversal is dated before the reversed movement."""

    def __init__(self, earliest: date) -> None:
        super().__init__(earliest)
        self.earliest = earliest


def reversal_type_for(target: Movement) -> MovementType:
    for reversal_type, reversed_type in REVERSAL_RULES.items():
        if reversed_type == target.type:
            return reversal_type
    raise NoReversalRuleError(target.type)


def chain_root(movement: Movement) -> Movement:
    """The first movement of the chain: two levels at most."""
    while movement.reverses is not None:
        movement = movement.reverses
    return movement


def _is_second_level(movement: Movement) -> bool:
    parent = movement.reverses
    return parent is not None and parent.reverses_id is not None


def can_reverse(user: User, target: Movement) -> bool:
    """The role rule alone: an operario never reverses a sale, a count
    adjustment, nor a reversal of either."""
    if user.role == UserRole.ADMIN:
        return True
    return chain_root(target).reason not in _ADMIN_ONLY_ROOT_REASONS


def _is_paid_sale(target: Movement) -> bool:
    """The sale itself, or the sale a reversal reverses (EARS-H3-07)."""
    root = chain_root(target)
    return root.reason == SALE_REASON and root.paid_at is not None


def reversal_block(user: User, target: Movement) -> ReversalBlock | None:
    """Why `user` cannot reverse `target`, or None if they can.

    One answer for the history's button (or its paid-sale notice) and for
    the server, so the two never disagree. Checked in this order: the role
    comes before the paid sale, so an operario sees no notice either.
    """
    if _is_second_level(target):
        return ReversalBlock.SECOND_LEVEL
    if not can_reverse(user, target):
        return ReversalBlock.NOT_ALLOWED
    if _is_paid_sale(target):
        return ReversalBlock.PAID_SALE
    if not target.material.is_active:
        return ReversalBlock.INACTIVE
    if target.remaining <= 0:
        return ReversalBlock.NOTHING_PENDING
    return None


# Blocks with their own error here; an inactive item and nothing pending
# fall to the usual rules below, with their usual messages.
_REJECTED_BLOCKS = (
    ReversalBlock.SECOND_LEVEL,
    ReversalBlock.NOT_ALLOWED,
    ReversalBlock.PAID_SALE,
)


def register_reversal(
    db: Session,
    *,
    target_id: int,
    quantity: str,
    movement_date: date,
    note: str | None,
    user: User,
) -> Movement:
    """Register a Reverso of `target_id`: of all of it or part of it.

    The item and the type are not asked for: they come from the reversed
    movement and from `REVERSAL_RULES`, so they cannot be wrong. Nothing is
    saved unless every rule passes.
    """
    target = db.get(Movement, target_id)
    if target is None:
        raise MovementNotFoundError(target_id)

    block = reversal_block(user, target)
    if block in _REJECTED_BLOCKS:
        assert block is not None
        raise ReversalBlockedError(block)

    parsed = parse_quantity(quantity)
    pending = target.remaining
    if parsed > pending:
        raise ReversalQuantityError(pending)
    if movement_date < target.movement_date:
        raise ReversalDateError(target.movement_date)

    # The usual rules too: an active item, a balance never negative.
    return register_movement(
        db,
        material=target.material,
        user=user,
        movement_type=reversal_type_for(target),
        quantity=parsed,
        movement_date=movement_date,
        note=note,
        reason=REVERSAL_REASON,
        reverses_id=target.id,
    )


def related_query(db: Session, movement_id: int) -> Query[Movement] | None:
    """The chain a movement belongs to: its root, the root's reversals and
    theirs, ordered like the history; None if it does not exist. A query, so
    the history can filter and page it like any other."""
    movement = db.get(Movement, movement_id)
    if movement is None:
        return None

    root = chain_root(movement)
    chain_ids = [root.id]
    level_ids = [root.id]
    for _ in range(2):
        level_ids = [
            child_id
            for (child_id,) in db.query(Movement.id).filter(
                Movement.reverses_id.in_(level_ids)
            )
        ]
        chain_ids += level_ids

    return (
        db.query(Movement)
        .filter(Movement.id.in_(chain_ids))
        .order_by(Movement.movement_date.desc(), Movement.id.desc())
    )


def related_movements(db: Session, movement_id: int) -> list[Movement]:
    """`related_query`, all of it; empty if the movement does not exist."""
    query = related_query(db, movement_id)
    return query.all() if query is not None else []
