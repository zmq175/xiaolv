"""Persist resolved-in-scope mention references with the outgoing intent."""

from alembic import op

revision = "0002_mentions"
down_revision = "0001_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE app.outbox ADD COLUMN mentions jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(mentions) = 'array')"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE app.outbox DROP COLUMN mentions")
