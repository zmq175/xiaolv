"""Persist the conversation-scoped quote reference with the outgoing intent."""

from alembic import op

revision = "0006_reply_to"
down_revision = "0005_model_budget"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE app.outbox ADD COLUMN reply_to text")


def downgrade() -> None:
    op.execute("ALTER TABLE app.outbox DROP COLUMN reply_to")
