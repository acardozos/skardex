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

# Why a salida happens. Only sales are charged. Stored as the key; the dict
# order is the order of the <select> in the movement form.
MOVEMENT_REASONS = {
    "venta": "Venta",
    "consumo_interno": "Consumo interno",
    "merma": "Merma",
    "desperdicio": "Desperdicio",
    "muestra": "Muestra",
    "otro": "Otro",
}
