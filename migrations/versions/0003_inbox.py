"""Persist normalized incoming events without advancing turn epochs."""

from alembic import op

revision = "0003_inbox"
down_revision = "0002_mentions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE app.conversation_state ADD COLUMN revision bigint NOT NULL DEFAULT 0")
    op.execute("""
        CREATE TABLE app.messages (
            conversation_id text NOT NULL REFERENCES app.conversation_state,
            message_id text NOT NULL,
            sequence bigint GENERATED ALWAYS AS IDENTITY,
            occurred_at timestamptz NOT NULL,
            payload jsonb NOT NULL,
            PRIMARY KEY (conversation_id, message_id)
        )
    """)
    op.execute(
        "CREATE INDEX messages_context ON app.messages (conversation_id, occurred_at DESC, sequence DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE app.messages")
    op.execute("ALTER TABLE app.conversation_state DROP COLUMN revision")
