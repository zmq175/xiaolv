"""Bound scanning of unfinished speech calls by original deadline."""

from alembic import op

revision = "0016_speech_recovery_index"
down_revision = "0015_speech_reconciliation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX speech_calls_pending_deadline ON app.speech_calls(expires_at, call_id) WHERE outcome IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX app.speech_calls_pending_deadline")
