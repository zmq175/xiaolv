"""Separate management session storage."""

from alembic import op

revision = "0010_admin_sessions"
down_revision = "0009_ordered_text"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA admin")
    op.execute("""CREATE TABLE admin.sessions (
        token_hash text PRIMARY KEY, csrf_token text NOT NULL,
        credential_version text NOT NULL, expires_at timestamptz NOT NULL
    )""")
    op.execute("CREATE INDEX admin_session_expiry ON admin.sessions(expires_at)")
    op.execute("""CREATE TABLE admin.login_window (
        id integer PRIMARY KEY CHECK (id = 1), began_at timestamptz NOT NULL,
        attempts integer NOT NULL CHECK (attempts > 0)
    )""")


def downgrade() -> None:
    op.execute("DROP TABLE admin.login_window")
    op.execute("DROP TABLE admin.sessions")
    op.execute("DROP SCHEMA admin")
