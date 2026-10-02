# Fixed list of measurement units, defined in code (not a DB table) per
# proj_docs/specs/001-mvp-kardex/plan.md. Values are user-facing (Spanish).
UNITS = [
    "kg",
    "g",
    "mg",
    "lb",
    "oz",
    "lt",
    "ml",
    "m3",
    "gl",
    "m",
    "m2",
    "pulg",
    "pie",
    "unidad",
    "caja",
    "rollo",
    "saco",
    "docena",
    "botella",
]

# Human-readable label per unit code, for display only (the stored/posted
# value is always the code in UNITS). Falls back to the code itself if a
# unit is ever added here without a label.
UNIT_LABELS: dict[str, str] = {
    "kg": "kg",
    "g": "g",
    "mg": "mg",
    "lb": "lb",
    "oz": "oz",
    "lt": "litro",
    "ml": "ml",
    "m3": "m³",
    "gl": "galón",
    "m": "m",
    "m2": "m²",
    "pulg": "pulgada",
    "pie": "pie",
    "unidad": "unidad",
    "caja": "caja",
    "rollo": "rollo",
    "saco": "saco",
    "docena": "docena",
    "botella": "botella",
}

SALE_REASON = "venta"
# Entrada or salida linked to the earlier movement it corrects, in whole or
# in part (spec 009). Registered only through the reversal service, never
# from the normal form, and never charged.
REVERSAL_REASON = "reverso"
# Entrada or salida that makes the system match a physical count (spec 009).
# Admin only, no link, never charged.
COUNT_ADJUSTMENT_REASON = "conteo"
# Legacy (spec 006): a correction with no link. Never offered nor accepted
# again; it only labels the movements that already have it.
ADJUSTMENT_REASON = "ajuste"

# Why an entrada happens, as offered and accepted in the movement form.
# Never charged, never affects billing. Stored as the key; the dict order is
# the order of its <select>.
ENTRADA_REASONS = {
    "compra": "Compra",
    "devolucion": "Devolución",
    COUNT_ADJUSTMENT_REASON: "Ajuste por conteo",
    "otro": "Otro",
}

# Why a salida happens, as offered and accepted in the movement form. Only
# sales are charged. Stored as the key; the dict order is the order of its
# <select>.
SALIDA_REASONS = {
    "venta": "Venta",
    "consumo_interno": "Consumo interno",
    "merma": "Merma",
    "desperdicio": "Desperdicio",
    "muestra": "Muestra",
    COUNT_ADJUSTMENT_REASON: "Ajuste por conteo",
    "otro": "Otro",
}

# Hidden from the operario in the form and rejected by the service.
ADMIN_ONLY_REASONS = frozenset({COUNT_ADJUSTMENT_REASON})

# What "Corregir cobro" offers and accepts: it reclassifies a salida for its
# billing, and a count adjustment is another kind of fact, registered as such.
BILLING_REASONS = {
    key: label
    for key, label in SALIDA_REASONS.items()
    if key != COUNT_ADJUSTMENT_REASON
}

# Salidas with these reasons are not consumption (spec 008, spec 009).
NOT_CONSUMPTION_REASONS = (
    ADJUSTMENT_REASON,
    REVERSAL_REASON,
    COUNT_ADJUSTMENT_REASON,
)

# Label lookup only (history, "Corregir cobro"): never used to populate a
# <select>, each screen has its own list above. Safe to merge because the
# keys both types share ("conteo", "otro") have the same label on both sides.
MOVEMENT_REASON_LABELS: dict[str, str] = {
    **ENTRADA_REASONS,
    **SALIDA_REASONS,
    REVERSAL_REASON: "Reverso",
    ADJUSTMENT_REASON: "Ajuste (sin vínculo)",
}
