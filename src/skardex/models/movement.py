import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from skardex.models.base import Base
from skardex.models.material import Material
from skardex.models.user import User


class MovementType(enum.StrEnum):
    ENTRADA = "entrada"
    SALIDA = "salida"


class Movement(Base):
    __tablename__ = "movements"

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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    material: Mapped[Material] = relationship()
    user: Mapped[User] = relationship()
