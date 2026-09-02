"""Add provenance for automatically promoted aliases."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_alias_promotion_provenance"
down_revision: str | None = "0004_single_active_resolution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("entity_aliases", sa.Column("source_mention_id", sa.Uuid(), nullable=True))
    op.add_column("entity_aliases", sa.Column("source_resolution_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_entity_aliases_source_mention",
        "entity_aliases",
        "entity_mentions",
        ["source_mention_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_entity_aliases_source_resolution",
        "entity_aliases",
        "entity_resolution_decisions",
        ["source_resolution_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_entity_aliases_source_resolution", "entity_aliases", type_="foreignkey")
    op.drop_constraint("fk_entity_aliases_source_mention", "entity_aliases", type_="foreignkey")
    op.drop_column("entity_aliases", "source_resolution_id")
    op.drop_column("entity_aliases", "source_mention_id")
