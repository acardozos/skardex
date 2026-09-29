from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from skardex.models.base import Base

# Each comparison is TRUE or FALSE, never NULL, so the CHECK cannot be
# passed by a half-filled alternate unit (a CHECK only fails on FALSE).
_ALT_UNIT_COMPLETE = " AND ".join(
    f"(({column} IS NULL) = (alt_unit_name IS NULL))"
    for column in (
        "alt_unit_factor",
        "alt_unit_reading",
        "alt_unit_read_at",
        "alt_unit_read_after_id",
    )
)


class Material(Base):
    __tablename__ = "materials"
    # Last line of defense for the alternate unit (spec 008); the material
    # service validates first and gives readable errors. Keep in sync with
    # the Alembic migration.
    __table_args__ = (
        CheckConstraint(_ALT_UNIT_COMPLETE, name="ck_materials_alt_unit_complete"),
        # With the complete-or-empty rule above, a reading always has a
        # factor, so the comparison never turns NULL. It also keeps the
        # factor positive (0 <= reading < factor), so that needs no CHECK
        # of its own.
        CheckConstraint(
            "alt_unit_reading IS NULL "
            "OR (alt_unit_reading >= 0 AND alt_unit_reading < alt_unit_factor)",
            name="ck_materials_alt_unit_reading_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    unit: Mapped[str] = mapped_column(String(20))
    min_stock: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    sale_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Alternate unit put into use (a roll of 30 m...), spec 008. All five are
    # set together or all left empty.
    alt_unit_name: Mapped[str | None] = mapped_column(String(30), nullable=True)
    alt_unit_factor: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 3), nullable=True
    )
    # What the open container had used at the last reading (the tirro).
    alt_unit_reading: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 3), nullable=True
    )
    alt_unit_read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Id of the last movement registered before the reading: Consumido only
    # counts movements with a greater id. 0 when there was none yet. An id,
    # not a time, so that two clocks (app and database) never disagree.
    alt_unit_read_after_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
