"""Shared model admission pools and deadline-bounded leases."""

from alembic import op

revision = "0008_model_capacity"
down_revision = "0007_delivery_quota"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE app.model_capacity_pools (
        pool_id text PRIMARY KEY, capacity integer NOT NULL CHECK (capacity > 0)
    )""")
    op.execute("""CREATE TABLE app.model_capacity_leases (
        call_id text PRIMARY KEY,
        pool_id text NOT NULL REFERENCES app.model_capacity_pools,
        lease_until timestamptz NOT NULL
    )""")
    op.execute(
        "CREATE INDEX model_capacity_expiry ON app.model_capacity_leases (pool_id, lease_until)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE app.model_capacity_leases")
    op.execute("DROP TABLE app.model_capacity_pools")
