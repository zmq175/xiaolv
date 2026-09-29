"""Durable candidates and conversational turn leases."""

from alembic import op

revision = "0004_candidates"
down_revision = "0003_inbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE app.conversation_state ADD COLUMN active_turn_id text, ADD COLUMN turn_lease_until timestamptz"
    )
    op.execute("""
        CREATE TABLE app.chat_candidates (
            conversation_id text PRIMARY KEY REFERENCES app.conversation_state,
            message_id text NOT NULL,
            pending_since timestamptz NOT NULL,
            ready_at timestamptz NOT NULL,
            expires_at timestamptz NOT NULL,
            queue_until timestamptz NOT NULL,
            FOREIGN KEY (conversation_id, message_id) REFERENCES app.messages
        )
    """)
    op.execute("""
        CREATE TABLE app.chat_turns (
            turn_id text PRIMARY KEY,
            conversation_id text NOT NULL REFERENCES app.conversation_state,
            epoch bigint NOT NULL,
            revision bigint NOT NULL,
            expires_at timestamptz NOT NULL,
            status text NOT NULL DEFAULT 'running',
            UNIQUE (conversation_id, epoch)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE app.chat_turns")
    op.execute("DROP TABLE app.chat_candidates")
    op.execute(
        "ALTER TABLE app.conversation_state DROP COLUMN active_turn_id, DROP COLUMN turn_lease_until"
    )
