"""permanent access codes

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("guests", sa.Column("pass_kind", sa.String(length=16), server_default="visitor", nullable=False))
    op.add_column("guests", sa.Column("valid_until", sa.Date(), nullable=True))
    op.create_index(op.f("ix_guests_pass_kind"), "guests", ["pass_kind"], unique=False)
    op.create_table(
        "pass_devices",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("pass_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["pass_id"], ["access_passes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("claim_hash"),
    )
    op.create_index(op.f("ix_pass_devices_pass_id"), "pass_devices", ["pass_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_pass_devices_pass_id"), table_name="pass_devices")
    op.drop_table("pass_devices")
    op.drop_index(op.f("ix_guests_pass_kind"), table_name="guests")
    op.drop_column("guests", "valid_until")
    op.drop_column("guests", "pass_kind")
