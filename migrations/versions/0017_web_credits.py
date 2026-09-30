"""Dedicated credit units for hosted search and extraction."""

from alembic import op

revision = "0017_web_credits"
down_revision = "0016_speech_recovery_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.web_credit_periods (
            pool_id text NOT NULL,
            period date NOT NULL,
            limit_credits numeric(20,6) NOT NULL CHECK (limit_credits > 0),
            reserved numeric(20,6) NOT NULL DEFAULT 0 CHECK (reserved >= 0),
            spent numeric(20,6) NOT NULL DEFAULT 0 CHECK (spent >= 0),
            blocked boolean NOT NULL DEFAULT false,
            PRIMARY KEY (pool_id, period)
        )
    """)
    op.execute("""
        CREATE TABLE app.web_credit_calls (
            call_id text PRIMARY KEY,
            pool_id text NOT NULL,
            period date NOT NULL,
            operation text NOT NULL CHECK (operation IN ('search', 'extract')),
            reserved numeric(20,6) NOT NULL CHECK (reserved > 0),
            charged numeric(20,6) CHECK (charged >= 0),
            state text NOT NULL DEFAULT 'reserved' CHECK (state IN ('reserved','settled','unknown')),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            expires_at timestamptz NOT NULL,
            finished_at timestamptz,
            FOREIGN KEY (pool_id, period) REFERENCES app.web_credit_periods
        )
    """)
    op.execute("CREATE INDEX web_credit_calls_period ON app.web_credit_calls(pool_id, period)")


def downgrade() -> None:
    op.execute("DROP TABLE app.web_credit_calls")
    op.execute("DROP TABLE app.web_credit_periods")
