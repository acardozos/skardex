"""How a movement is named inside a sentence of the UI (spec 009): "venta
#123", "la venta #123", "del reverso #130". By its reason when that names
what happened, by its type otherwise ("Otro", or no reason at all)."""

from skardex.constants import (
    ADJUSTMENT_REASON,
    COUNT_ADJUSTMENT_REASON,
    MOVEMENT_REASON_LABELS,
    REVERSAL_REASON,
)
from skardex.models import Movement

# Reasons whose noun is masculine in Spanish; every other noun, and both
# types ("entrada", "salida"), is feminine.
_MASCULINE_REASONS = frozenset(
    {
        "consumo_interno",
        "desperdicio",
        COUNT_ADJUSTMENT_REASON,
        REVERSAL_REASON,
        ADJUSTMENT_REASON,
    }
)
# The legacy label carries "(sin vínculo)", which reads badly mid-sentence.
_NOUN_OVERRIDES = {ADJUSTMENT_REASON: "ajuste"}
# Too vague to name a movement by.
_TYPE_INSTEAD = frozenset({None, "otro"})


def _is_named_by_reason(movement: Movement) -> bool:
    return (
        movement.reason not in _TYPE_INSTEAD
        and movement.reason in MOVEMENT_REASON_LABELS
    )


def movement_ref(movement: Movement) -> str:
    """ "venta #123", "consumo interno #45", "entrada #7"."""
    if _is_named_by_reason(movement):
        assert movement.reason is not None
        noun = _NOUN_OVERRIDES.get(
            movement.reason, MOVEMENT_REASON_LABELS[movement.reason].lower()
        )
    else:
        noun = movement.type.value
    return f"{noun} #{movement.id}"


def _is_masculine(movement: Movement) -> bool:
    return _is_named_by_reason(movement) and movement.reason in _MASCULINE_REASONS


def with_article(movement: Movement) -> str:
    """ "la venta #123", "el reverso #130"."""
    article = "el" if _is_masculine(movement) else "la"
    return f"{article} {movement_ref(movement)}"


def of_ref(movement: Movement) -> str:
    """ "de la venta #123", "del reverso #130"."""
    prefix = "del" if _is_masculine(movement) else "de la"
    return f"{prefix} {movement_ref(movement)}"
