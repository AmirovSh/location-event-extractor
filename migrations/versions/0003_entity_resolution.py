"""Add scoped canonical entities and reversible resolution decisions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_entity_resolution"
down_revision: str | None = "0002_candidate_semantics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "canonical_entities",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.String(512), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_canonical_entities_tenant_type",
        "canonical_entities",
        ["tenant_id", "entity_type"],
    )
    op.create_table(
        "entity_aliases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "canonical_entity_id",
            sa.Uuid(),
            sa.ForeignKey("canonical_entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(512), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("normalized_alias", sa.Text(), nullable=False),
        sa.Column("source_id", sa.String(512), nullable=True),
        sa.Column("conversation_id", sa.String(512), nullable=True),
        sa.Column("sender_id", sa.String(512), nullable=True),
        sa.Column("alias_source", sa.String(32), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_entity_aliases_lookup",
        "entity_aliases",
        ["tenant_id", "entity_type", "normalized_alias", "active"],
    )
    op.create_table(
        "entity_mentions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("mention_text", sa.Text(), nullable=False),
        sa.Column("normalized_mention", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.String(512), nullable=False),
        sa.Column("source_id", sa.String(512), nullable=True),
        sa.Column("conversation_id", sa.String(512), nullable=True),
        sa.Column("sender_id", sa.String(512), nullable=True),
        sa.Column(
            "source_message_id",
            sa.Uuid(),
            sa.ForeignKey("source_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("context_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_entity_mentions_scope",
        "entity_mentions",
        ["tenant_id", "source_id", "conversation_id"],
    )
    op.create_table(
        "entity_resolution_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "mention_id",
            sa.Uuid(),
            sa.ForeignKey("entity_mentions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("confidence", sa.String(32), nullable=False),
        sa.Column(
            "canonical_entity_id",
            sa.Uuid(),
            sa.ForeignKey("canonical_entities.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("candidate_entity_ids", sa.JSON(), nullable=False),
        sa.Column("factors", sa.JSON(), nullable=False),
        sa.Column("resolver_version", sa.String(128), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "supersedes_resolution_id",
            sa.Uuid(),
            sa.ForeignKey("entity_resolution_decisions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_entity_resolution_decisions_mention_active",
        "entity_resolution_decisions",
        ["mention_id", "active"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_entity_resolution_decisions_mention_active",
        table_name="entity_resolution_decisions",
    )
    op.drop_table("entity_resolution_decisions")
    op.drop_index("ix_entity_mentions_scope", table_name="entity_mentions")
    op.drop_table("entity_mentions")
    op.drop_index("ix_entity_aliases_lookup", table_name="entity_aliases")
    op.drop_table("entity_aliases")
    op.drop_index("ix_canonical_entities_tenant_type", table_name="canonical_entities")
    op.drop_table("canonical_entities")
