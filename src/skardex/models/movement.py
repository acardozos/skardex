import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    material: Mapped[Material] = relationship()
    # Two foreign keys point at users, so each relationship must say which one.
    user: Mapped[User] = relationship(foreign_keys=[user_id])
    paid_by: Mapped[User | None] = relationship(foreign_keys=[paid_by_id])

    @property
    def amount(self) -> Decimal | None:
        if self.unit_price is None:
            return None
        return line_amount(self.quantity, self.unit_price)
