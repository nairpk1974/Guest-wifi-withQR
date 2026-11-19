"""FortiGate device lookup for Wi-Fi requests

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("locations", sa.Column("api_url", sa.String(length=120), nullable=True))
    op.add_column("guests", sa.Column("request_mac", sa.String(length=32), nullable=True))
    op.add_column("guests", sa.Column("request_hostname", sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column("guests", "request_hostname")
    op.drop_column("guests", "request_mac")
    op.drop_column("locations", "api_url")
