"""Allow only one active resolution decision for a mention."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_single_active_resolution"
down_revision: str | None = "0003_entity_resolution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(
        "ix_entity_resolution_decisions_mention_active",
        table_name="entity_resolution_decisions",
    )
    op.create_index(
        "ux_entity_resolution_decisions_active_mention",
        "entity_resolution_decisions",
        ["mention_id"],
        unique=True,
        postgresql_where=sa.text("active"),
        sqlite_where=sa.text("active"),
    )


def downgrade() -> None:
    op.drop_index(
        "ux_entity_resolution_decisions_active_mention",
        table_name="entity_resolution_decisions",
    )
    op.create_index(
        "ix_entity_resolution_decisions_mention_active",
        "entity_resolution_decisions",
        ["mention_id", "active"],
    )
