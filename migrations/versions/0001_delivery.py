"""Persist conversation epochs and delivery claims."""

from alembic import op

revision = "0001_delivery"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS app")
    op.execute("""
        CREATE TABLE app.conversation_state (
            conversation_id text PRIMARY KEY,
            epoch bigint NOT NULL DEFAULT 0 CHECK (epoch >= 0)
        )
    """)
    op.execute("""
        CREATE TABLE app.outbox (
            outgoing_id text PRIMARY KEY,
            conversation_id text NOT NULL REFERENCES app.conversation_state,
            expires_at timestamptz NOT NULL,
            generation_epoch bigint NOT NULL,
            body text NOT NULL,
            status text NOT NULL CHECK (status IN
                ('sending', 'confirmed', 'unknown', 'expired', 'superseded', 'not_sent')),
            attempt_token text NOT NULL,
            lease_until timestamptz NOT NULL
        )
    """)
    op.execute(
        "CREATE INDEX outbox_inflight_lease ON app.outbox (lease_until) WHERE status = 'sending'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE app.outbox")
    op.execute("DROP TABLE app.conversation_state")
