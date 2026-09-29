"""Conversation quota accounting from durable outgoing claims."""

from alembic import op

revision = "0007_delivery_quota"
down_revision = "0006_reply_to"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE app.outbox ADD COLUMN claimed_at timestamptz NOT NULL DEFAULT clock_timestamp()"
    )
    op.execute("ALTER TABLE app.outbox DROP CONSTRAINT outbox_status_check")
    op.execute("""ALTER TABLE app.outbox ADD CONSTRAINT outbox_status_check CHECK
        (status IN ('sending', 'confirmed', 'unknown', 'expired', 'superseded', 'not_sent', 'rate_limited'))""")
    op.execute("""CREATE INDEX outbox_quota ON app.outbox (conversation_id, claimed_at)
        WHERE status IN ('sending', 'confirmed', 'unknown')""")


def downgrade() -> None:
    op.execute("DROP INDEX app.outbox_quota")
    op.execute("UPDATE app.outbox SET status = 'not_sent' WHERE status = 'rate_limited'")
    op.execute("ALTER TABLE app.outbox DROP CONSTRAINT outbox_status_check")
    op.execute("""ALTER TABLE app.outbox ADD CONSTRAINT outbox_status_check CHECK
        (status IN ('sending', 'confirmed', 'unknown', 'expired', 'superseded', 'not_sent'))""")
    op.execute("ALTER TABLE app.outbox DROP COLUMN claimed_at")
