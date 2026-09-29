"""Durable speech execution and independently auditable monetary reservations."""

from alembic import op

revision = "0013_speech_calls"
down_revision = "0012_conversation_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE app.speech_calls (
        call_id text PRIMARY KEY, request_hash text NOT NULL,
        conversation_id text NOT NULL, generation_epoch bigint NOT NULL,
        expires_at timestamptz NOT NULL,
        pool_id text NOT NULL, period date NOT NULL,
        provider_id text NOT NULL, model text NOT NULL,
        price_version text NOT NULL, voice_binding_version text NOT NULL,
        reserved_amount numeric(20,6) NOT NULL CHECK (reserved_amount >= 0),
        charged_amount numeric(20,6) CHECK (charged_amount >= 0),
        state text NOT NULL DEFAULT 'running', outcome text,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        FOREIGN KEY (pool_id, period) REFERENCES app.budget_periods
    )""")
    op.execute("CREATE INDEX speech_calls_period ON app.speech_calls(pool_id, period)")


def downgrade() -> None:
    op.execute("DROP TABLE app.speech_calls")
