"""seed office locations

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# coa_host / portal_post_hosts / monitor_host are deliberately left empty: they are set by the
# Super Administrator (Settings -> Locations) only after the FortiGate discovery has confirmed the real
# interface addresses. With an empty portal_post_hosts list the guest portal refuses to post credentials.


def upgrade() -> None:
    locations = sa.table("locations", sa.column("code", sa.String), sa.column("name", sa.String),
                         sa.column("ssid", sa.String), sa.column("timezone", sa.String),
                         sa.column("nas_shortname", sa.String), sa.column("coa_port", sa.Integer),
                         sa.column("portal_post_hosts", sa.JSON), sa.column("enabled", sa.Boolean))
    op.bulk_insert(locations, [
        {"code": "BLR", "name": "Head Office - Bangalore", "ssid": "BESSEL-GUEST-BLR", "timezone": "Asia/Kolkata",
         "nas_shortname": "fgt-blr", "coa_port": 3799, "portal_post_hosts": [], "enabled": True},
        {"code": "HYD", "name": "Branch Office - Hyderabad", "ssid": "BESSEL-GUEST-HYD", "timezone": "Asia/Kolkata",
         "nas_shortname": "fgt-hyd", "coa_port": 3799, "portal_post_hosts": [], "enabled": True},
    ])


def downgrade() -> None:
    op.execute("DELETE FROM locations WHERE code IN ('BLR', 'HYD')")
