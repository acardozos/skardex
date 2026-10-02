import enum
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    select,
    type_coerce,
)
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from skardex.models.base import Base
from skardex.models.material import Material
from skardex.models.user import User
from skardex.money import line_amount


class MovementType(enum.StrEnum):
    ENTRADA = "entrada"
    SALIDA = "salida"


class Movement(Base):
    __tablename__ = "movements"
    # Last line of defense for money data; the billing service validates first
    # and gives readable errors. Keep in sync with the Alembic migration.
    # COALESCE matters: a CHECK only fails on FALSE, and `NULL = 'venta'` is
    # NULL, which would let a price through on a movement with no reason.
    __table_args__ = (
        CheckConstraint(
            "unit_price IS NULL OR unit_price > 0",
            name="ck_movements_unit_price_positive",
        ),
        CheckConstraint(
            "paid_at IS NULL OR unit_price IS NOT NULL",
            name="ck_movements_paid_requires_price",
        ),
        CheckConstraint(
            (
                "(unit_price IS NULL AND paid_at IS NULL) "
                "OR COALESCE(reason, '') = 'venta'"
            ),
            name="ck_movements_billing_only_for_sales",
        ),
        # A link (`reverses_id`) only says "this movement offsets that one";
        # which reasons may carry it is the reversal service's rule, so the
        # schema never mentions a reason (spec 010 adds Traslado without a
        # migration). The pair is already unique because `id` is; Postgres
        # still needs it declared to be the target of a foreign key.
        UniqueConstraint("id", "material_id", name="uq_movements_id_material"),
        # Two columns, so a link can only point at a movement of the same
        # material. With `reverses_id` NULL the key is not checked.
        ForeignKeyConstraint(
            ["reverses_id", "material_id"],
            ["movements.id", "movements.material_id"],
            name="fk_movements_reverses_same_material",
        ),
        CheckConstraint(
            "reverses_id IS NULL OR reverses_id <> id",
            name="ck_movements_not_self_reverse",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    type: Mapped[MovementType] = mapped_column(
        Enum(
            MovementType,
            name="movement_type",
            values_callable=lambda e: [m.value for m in e],
        )
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    movement_date: Mapped[date] = mapped_column(Date, default=date.today)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(20), nullable=True)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    paid_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    paid_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    reverses_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    material: Mapped[Material] = relationship()
    # Two foreign keys point at users, so each relationship must say which one.
    user: Mapped[User] = relationship(foreign_keys=[user_id])
    paid_by: Mapped[User | None] = relationship(foreign_keys=[paid_by_id])

    if TYPE_CHECKING:
        # Mapped below the class: it queries this same table.
        reversed_quantity: Mapped[Decimal]

    @property
    def remaining(self) -> Decimal:
        """Quantity minus what was reversed: what is left to reverse.

        A movement not yet saved has no reversals, and no loaded value.
        """
        return self.quantity - (self.reversed_quantity or Decimal("0"))

    @property
    def is_fully_reversed(self) -> bool:
        return self.remaining == 0

    @property
    def amount(self) -> Decimal | None:
        """What is charged: what is left of the sale, by its price."""
        if self.unit_price is None:
            return None
        return line_amount(self.remaining, self.unit_price)


# What was reversed of a movement, computed on read like the balance, never
# stored: the sum of its reversals, each minus what was in turn reversed of
# it. Two levels are enough: a reversal of a reversal cannot be reversed.
_reversal = Movement.__table__.alias("reversal")
_counter_reversal = Movement.__table__.alias("counter_reversal")
_counter_reversed = (
    select(func.coalesce(func.sum(_counter_reversal.c.quantity), 0))
    .where(_counter_reversal.c.reverses_id == _reversal.c.id)
    .correlate(_reversal)
    .scalar_subquery()
)
Movement.reversed_quantity = column_property(
    select(
        # Numeric, so SQLite (which sums as float) returns a 3-decimal Decimal.
        type_coerce(
            func.coalesce(func.sum(_reversal.c.quantity - _counter_reversed), 0),
            Numeric(12, 3),
        )
    )
    .where(_reversal.c.reverses_id == Movement.id)
    .correlate_except(_reversal)
    .scalar_subquery()
)
