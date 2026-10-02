"""add reverses_id to movements

Revision ID: 9a4c6e2b8f15
Revises: 5c8e2f71a9d4
Create Date: 2026-10-01 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9a4c6e2b8f15"
down_revision: str | Sequence[str] | None = "5c8e2f71a9d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Existing movements keep no link: no data is touched.
    op.add_column("movements", sa.Column("reverses_id", sa.Integer(), nullable=True))
    op.create_index("ix_movements_reverses_id", "movements", ["reverses_id"])

    # A foreign key needs a declared unique target; `id` alone already is.
    op.create_unique_constraint(
        "uq_movements_id_material", "movements", ["id", "material_id"]
    )
    # Same material only. Nothing here mentions a reason: which movements may
    # carry a link is the reversal service's rule.
    op.create_foreign_key(
        "fk_movements_reverses_same_material",
        "movements",
        "movements",
        ["reverses_id", "material_id"],
        ["id", "material_id"],
    )
    op.create_check_constraint(
        "ck_movements_not_self_reverse",
        "movements",
        "reverses_id IS NULL OR reverses_id <> id",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_movements_not_self_reverse", "movements")
    op.drop_constraint("fk_movements_reverses_same_material", "movements")
    op.drop_constraint("uq_movements_id_material", "movements")
    op.drop_index("ix_movements_reverses_id", "movements")
    op.drop_column("movements", "reverses_id")
