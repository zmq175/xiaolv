"""Private drafts and chat-readable immutable profile releases."""

from alembic import op

revision = "0011_profile_publication"
down_revision = "0010_admin_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE admin.profile_state (
        id integer PRIMARY KEY CHECK (id = 1), revision bigint NOT NULL, draft jsonb
    )""")
    op.execute("INSERT INTO admin.profile_state(id, revision) VALUES (1, 0)")
    op.execute("""CREATE TABLE app.bot_profile_releases (
        version bigserial PRIMARY KEY, profile jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp()
    )""")
    op.execute("""CREATE TABLE app.bot_profile_current (
        id integer PRIMARY KEY CHECK (id = 1),
        version bigint REFERENCES app.bot_profile_releases(version)
    )""")
    op.execute("INSERT INTO app.bot_profile_current(id) VALUES (1)")
    op.execute("""CREATE TABLE admin.profile_mutations (
        idempotency_key text PRIMARY KEY, request_hash text NOT NULL, response jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp()
    )""")


def downgrade() -> None:
    op.execute("DROP TABLE admin.profile_mutations")
    op.execute("DROP TABLE app.bot_profile_current")
    op.execute("DROP TABLE app.bot_profile_releases")
    op.execute("DROP TABLE admin.profile_state")
