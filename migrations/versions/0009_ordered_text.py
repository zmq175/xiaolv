"""Persist ordered text intent for idempotency across restarts."""

from alembic import op

revision = "0009_ordered_text"
down_revision = "0008_model_capacity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE app.outbox ADD COLUMN parts jsonb NOT NULL DEFAULT '[]'::jsonb")


def downgrade() -> None:
    # Dropping populated intent would hide payload conflicts on subsequent retries.
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM app.outbox WHERE parts <> '[]'::jsonb) THEN
            RAISE EXCEPTION 'ordered outbox data requires archival before downgrade';
        END IF;
    END $$""")
    op.execute("ALTER TABLE app.outbox DROP COLUMN parts")
