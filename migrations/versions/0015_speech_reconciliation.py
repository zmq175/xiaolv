"""Immutable management evidence for settling previously unknown speech costs."""

from alembic import op

revision = "0015_speech_reconciliation"
down_revision = "0014_outbox_audio"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE admin.speech_reconciliations (
        call_id text PRIMARY KEY REFERENCES app.speech_calls,
        idempotency_key text NOT NULL, request_hash text NOT NULL,
        charged_amount numeric(20,6) NOT NULL CHECK(charged_amount >= 0),
        evidence text NOT NULL, actor text NOT NULL, response jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp()
    )""")


def downgrade() -> None:
    op.execute("DROP TABLE admin.speech_reconciliations")
