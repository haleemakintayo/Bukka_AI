"""Add processed webhook events table

Revision ID: 8e5c1d2a9f44
Revises: 37bc529ad715
Create Date: 2026-03-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8e5c1d2a9f44"
down_revision: Union[str, Sequence[str], None] = "37bc529ad715"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "processed_webhook_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("external_event_id", sa.String(), nullable=False),
        sa.Column("claimed_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform", "external_event_id", name="uq_processed_webhook_event"),
    )
    op.create_index(op.f("ix_processed_webhook_events_id"), "processed_webhook_events", ["id"], unique=False)
    op.create_index(op.f("ix_processed_webhook_events_platform"), "processed_webhook_events", ["platform"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_processed_webhook_events_platform"), table_name="processed_webhook_events")
    op.drop_index(op.f("ix_processed_webhook_events_id"), table_name="processed_webhook_events")
    op.drop_table("processed_webhook_events")
