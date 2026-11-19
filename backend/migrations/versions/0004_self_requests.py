"""self-service Wi-Fi access requests

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("guests", sa.Column("source", sa.String(length=16), server_default="reception", nullable=False))
    op.add_column("guests", sa.Column("request_claim_hash", sa.String(length=64), nullable=True))
    op.add_column("guests", sa.Column("request_ip", sa.String(length=64), nullable=True))
    op.add_column("guests", sa.Column("request_device", sa.String(length=120), nullable=True))
    op.add_column("guests", sa.Column("request_user_agent", sa.String(length=255), nullable=True))
    op.create_unique_constraint("guests_request_claim_hash_key", "guests", ["request_claim_hash"])


def downgrade() -> None:
    op.drop_constraint("guests_request_claim_hash_key", "guests", type_="unique")
    op.drop_column("guests", "request_user_agent")
    op.drop_column("guests", "request_device")
    op.drop_column("guests", "request_ip")
    op.drop_column("guests", "request_claim_hash")
    op.drop_column("guests", "source")
