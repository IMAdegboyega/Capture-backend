"""add comments, video password/embed/processing status

Revision ID: 2026042001
Revises: 862e3e87a949
Create Date: 2026-04-20 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2026042001"
down_revision: Union[str, None] = "862e3e87a949"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Video additions ────────────────────────────────────────────────────
    op.add_column(
        "videos",
        sa.Column("password_hash", sa.String(), nullable=True),
    )
    op.add_column(
        "videos",
        sa.Column(
            "embed_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "videos",
        sa.Column(
            "processing_status",
            sa.String(),
            nullable=False,
            server_default=sa.text("'ready'"),
        ),
    )
    op.add_column(
        "videos",
        sa.Column(
            "processing_progress",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("100"),
        ),
    )

    # ── Comments table ─────────────────────────────────────────────────────
    op.create_table(
        "video_comments",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("video_pk", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("timestamp_seconds", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["video_pk"], ["videos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_video_comments_video_pk", "video_comments", ["video_pk"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_video_comments_video_pk", table_name="video_comments")
    op.drop_table("video_comments")
    op.drop_column("videos", "processing_progress")
    op.drop_column("videos", "processing_status")
    op.drop_column("videos", "embed_enabled")
    op.drop_column("videos", "password_hash")
