"""Persistent management overrides for registered conversations."""

from alembic import op

revision = "0012_conversation_control"
down_revision = "0011_profile_publication"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE app.conversation_controls (
        conversation_id text PRIMARY KEY REFERENCES app.conversation_state,
        enabled boolean NOT NULL DEFAULT true, revision bigint NOT NULL DEFAULT 0
    )""")
    op.execute("""CREATE TABLE admin.conversation_mutations (
        conversation_id text NOT NULL REFERENCES app.conversation_controls,
        idempotency_key text NOT NULL, request_hash text NOT NULL, response jsonb NOT NULL,
        actor text NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        PRIMARY KEY (conversation_id, idempotency_key)
    )""")


def downgrade() -> None:
    op.execute("DROP TABLE admin.conversation_mutations")
    op.execute("DROP TABLE app.conversation_controls")
