"""Persist immutable audio references alongside the delivery intent."""

from alembic import op

revision = "0014_outbox_audio"
down_revision = "0013_speech_calls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE app.outbox ADD COLUMN audio jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE app.outbox DROP COLUMN audio")
