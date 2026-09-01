"""Initial auditable location event schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _candidate_columns() -> list[sa.Column[object]]:
    return [
        sa.Column("person_mention", sa.Text(), nullable=True),
        sa.Column("location_mention", sa.Text(), nullable=True),
        sa.Column("relation", sa.String(32), nullable=False),
        sa.Column("certainty", sa.String(32), nullable=False),
        sa.Column("location_type", sa.String(32), nullable=False),
        sa.Column("temporal_raw", sa.Text(), nullable=True),
        sa.Column("evidence_text", sa.Text(), nullable=True),
        sa.Column("evidence_start", sa.Integer(), nullable=True),
        sa.Column("evidence_end", sa.Integer(), nullable=True),
        sa.Column("ambiguous", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ambiguity_reason", sa.Text(), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "source_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("external_message_id", sa.String(512), nullable=False),
        sa.Column("conversation_id", sa.String(512), nullable=False),
        sa.Column("author_id", sa.String(512), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("text_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("conversation_id", "external_message_id", name="uq_source_message"),
    )
    op.create_table(
        "extraction_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "source_message_id",
            sa.Uuid(),
            sa.ForeignKey("source_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("extractor_version", sa.String(128), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("extractor_provider", sa.String(128), nullable=True),
        sa.Column("extractor_model", sa.String(256), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "source_message_id",
            "extractor_version",
            "schema_version",
            name="uq_extraction_run_version",
        ),
    )
    op.create_index(
        "ix_extraction_runs_status_created", "extraction_runs", ["status", "created_at"]
    )
    op.create_table(
        "location_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "source_message_id",
            sa.Uuid(),
            sa.ForeignKey("source_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "extraction_run_id",
            sa.Uuid(),
            sa.ForeignKey("extraction_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        *_candidate_columns(),
        sa.Column("extractor_version", sa.String(128), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_location_events_source_message", "location_events", ["source_message_id"])
    op.create_table(
        "extraction_rejections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "extraction_run_id",
            sa.Uuid(),
            sa.ForeignKey("extraction_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        *_candidate_columns(),
        sa.Column("rejection_reason", sa.String(64), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("extraction_rejections")
    op.drop_index("ix_location_events_source_message", table_name="location_events")
    op.drop_table("location_events")
    op.drop_index("ix_extraction_runs_status_created", table_name="extraction_runs")
    op.drop_table("extraction_runs")
    op.drop_table("source_messages")
