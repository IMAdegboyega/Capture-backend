import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "user"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True)
    email_verified = Column(Boolean, nullable=False, default=False)
    image = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    accounts = relationship("Account", back_populates="user", cascade="all, delete-orphan")
    videos = relationship("Video", back_populates="user", cascade="all, delete-orphan")


class Session(Base):
    __tablename__ = "session"

    id = Column(String, primary_key=True)
    expires_at = Column(DateTime, nullable=False)
    token = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    user_id = Column(String, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)

    user = relationship("User", back_populates="sessions")


class Account(Base):
    __tablename__ = "account"

    id = Column(String, primary_key=True)
    account_id = Column(String, nullable=False)
    provider_id = Column(String, nullable=False)
    user_id = Column(String, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    access_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    id_token = Column(Text, nullable=True)
    access_token_expires_at = Column(DateTime, nullable=True)
    refresh_token_expires_at = Column(DateTime, nullable=True)
    scope = Column(String, nullable=True)
    password = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    user = relationship("User", back_populates="accounts")


class Verification(Base):
    __tablename__ = "verification"

    id = Column(String, primary_key=True)
    identifier = Column(String, nullable=False)
    value = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)


class Video(Base):
    __tablename__ = "videos"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        server_default=text("gen_random_uuid()"),
    )
    title = Column(String, nullable=False)
    description = Column(String, nullable=False)
    video_url = Column(String, nullable=False)
    video_id = Column(String, nullable=False)
    thumbnail_url = Column(String, nullable=False)
    visibility = Column(String, nullable=False, default="public")
    user_id = Column(String, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    views = Column(Integer, nullable=False, default=0)
    duration = Column(Integer, nullable=True)
    # Password protection — when set, viewers must POST the password to unlock
    password_hash = Column(String, nullable=True)
    # Whether embedding via iframe is permitted. Defaults to True.
    embed_enabled = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    # Persisted Cloudinary processing status, written by webhook to avoid polling Cloudinary
    processing_status = Column(
        String, nullable=False, default="ready", server_default=text("'ready'")
    )
    processing_progress = Column(
        Integer, nullable=False, default=100, server_default=text("100")
    )
    created_at = Column(DateTime, nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("now()"))

    user = relationship("User", back_populates="videos")
    comments = relationship(
        "Comment", back_populates="video", cascade="all, delete-orphan"
    )


class Comment(Base):
    """
    A comment on a video. Supports optional timestamp_seconds so users can
    anchor their comment to a specific moment in the recording.
    """
    __tablename__ = "video_comments"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        server_default=text("gen_random_uuid()"),
    )
    video_pk = Column(
        UUID(as_uuid=True),
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        String, ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    body = Column(Text, nullable=False)
    # Seconds offset into the video, or NULL for a general comment
    timestamp_seconds = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("now()"))

    video = relationship("Video", back_populates="comments")
    user = relationship("User")
