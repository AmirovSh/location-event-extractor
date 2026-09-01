"""Add structured reference and polarity semantics."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_candidate_semantics"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("location_events", "extraction_rejections"):
        op.add_column(
            table,
            sa.Column(
                "person_reference",
                sa.String(32),
                nullable=False,
                server_default="EXPLICIT",
            ),
        )
        op.add_column(
            table,
            sa.Column(
                "location_reference",
                sa.String(32),
                nullable=False,
                server_default="EXPLICIT",
            ),
        )
        op.add_column(
            table,
            sa.Column("polarity", sa.String(32), nullable=False, server_default="POSITIVE"),
        )


def downgrade() -> None:
    for table in ("extraction_rejections", "location_events"):
        op.drop_column(table, "polarity")
        op.drop_column(table, "location_reference")
        op.drop_column(table, "person_reference")
