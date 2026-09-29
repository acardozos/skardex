"""add alt unit to materials

Revision ID: 5c8e2f71a9d4
Revises: 7d2f4a9c1e63
Create Date: 2026-09-29 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5c8e2f71a9d4"
down_revision: str | Sequence[str] | None = "7d2f4a9c1e63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Written out rather than imported from the model: a migration must keep
# meaning the same even if the model changes later.
ALT_UNIT_COMPLETE = (
    "((alt_unit_factor IS NULL) = (alt_unit_name IS NULL))"
    " AND ((alt_unit_reading IS NULL) = (alt_unit_name IS NULL))"
    " AND ((alt_unit_read_at IS NULL) = (alt_unit_name IS NULL))"
    " AND ((alt_unit_read_after_id IS NULL) = (alt_unit_name IS NULL))"
)


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("materials", sa.Column("alt_unit_name", sa.String(30), nullable=True))
    op.add_column(
        "materials", sa.Column("alt_unit_factor", sa.Numeric(12, 3), nullable=True)
    )
    op.add_column(
        "materials", sa.Column("alt_unit_reading", sa.Numeric(12, 3), nullable=True)
    )
    op.add_column(
        "materials",
        sa.Column("alt_unit_read_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "materials", sa.Column("alt_unit_read_after_id", sa.Integer(), nullable=True)
    )

    op.create_check_constraint(
        "ck_materials_alt_unit_complete", "materials", ALT_UNIT_COMPLETE
    )
    # Also keeps the factor positive (0 <= reading < factor).
    op.create_check_constraint(
        "ck_materials_alt_unit_reading_range",
        "materials",
        "alt_unit_reading IS NULL "
        "OR (alt_unit_reading >= 0 AND alt_unit_reading < alt_unit_factor)",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_materials_alt_unit_reading_range", "materials")
    op.drop_constraint("ck_materials_alt_unit_complete", "materials")
    op.drop_column("materials", "alt_unit_read_after_id")
    op.drop_column("materials", "alt_unit_read_at")
    op.drop_column("materials", "alt_unit_reading")
    op.drop_column("materials", "alt_unit_factor")
    op.drop_column("materials", "alt_unit_name")
