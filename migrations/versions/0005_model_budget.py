"""Persistent monthly budget reservations and model call audit."""

from alembic import op

revision = "0005_model_budget"
down_revision = "0004_candidates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.budget_periods (
            pool_id text NOT NULL,
            period date NOT NULL,
            limit_amount numeric(20,6) NOT NULL CHECK (limit_amount >= 0),
            reserved numeric(20,6) NOT NULL DEFAULT 0 CHECK (reserved >= 0),
            spent numeric(20,6) NOT NULL DEFAULT 0 CHECK (spent >= 0),
            blocked boolean NOT NULL DEFAULT false,
            PRIMARY KEY (pool_id, period)
        )
    """)
    op.execute("""
        CREATE TABLE app.model_calls (
            call_id text PRIMARY KEY,
            pool_id text NOT NULL,
            period date NOT NULL,
            provider_id text NOT NULL,
            model text NOT NULL,
            price_version text NOT NULL,
            input_rate numeric(20,6) NOT NULL,
            output_rate numeric(20,6) NOT NULL,
            cached_rate numeric(20,6),
            reserved_amount numeric(20,6) NOT NULL,
            charged_amount numeric(20,6),
            state text NOT NULL DEFAULT 'reserved' CHECK (state IN ('reserved','settled','unknown')),
            started_at timestamptz NOT NULL,
            report jsonb,
            FOREIGN KEY (pool_id, period) REFERENCES app.budget_periods
        )
    """)
    op.execute("CREATE INDEX model_calls_period ON app.model_calls (pool_id, period)")


def downgrade() -> None:
    op.execute("DROP TABLE app.model_calls")
    op.execute("DROP TABLE app.budget_periods")
