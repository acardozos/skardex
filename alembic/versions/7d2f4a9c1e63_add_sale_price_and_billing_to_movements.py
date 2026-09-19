"""add sale price and billing to movements

Revision ID: 7d2f4a9c1e63
Revises: 3b7e91c4d2a8
Create Date: 2026-09-19 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7d2f4a9c1e63"
down_revision: str | Sequence[str] | None = "3b7e91c4d2a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "materials", sa.Column("sale_price", sa.Numeric(14, 2), nullable=True)
    )

    op.add_column("movements", sa.Column("reason", sa.String(20), nullable=True))
    op.add_column(
        "movements", sa.Column("unit_price", sa.Numeric(14, 2), nullable=True)
    )
    op.add_column("movements", sa.Column("paid_at", sa.Date(), nullable=True))
    op.add_column("movements", sa.Column("paid_by_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_movements_paid_by_id_users", "movements", "users", ["paid_by_id"], ["id"]
    )

    op.create_check_constraint(
        "ck_movements_unit_price_positive",
        "movements",
        "unit_price IS NULL OR unit_price > 0",
    )
    op.create_check_constraint(
        "ck_movements_paid_requires_price",
        "movements",
        "paid_at IS NULL OR unit_price IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_movements_billing_only_for_sales",
        "movements",
        ("(unit_price IS NULL AND paid_at IS NULL) OR COALESCE(reason, '') = 'venta'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_movements_billing_only_for_sales", "movements")
    op.drop_constraint("ck_movements_paid_requires_price", "movements")
    op.drop_constraint("ck_movements_unit_price_positive", "movements")
    op.drop_constraint("fk_movements_paid_by_id_users", "movements")
    op.drop_column("movements", "paid_by_id")
    op.drop_column("movements", "paid_at")
    op.drop_column("movements", "unit_price")
    op.drop_column("movements", "reason")
    op.drop_column("materials", "sale_price")
