from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


# ─── Auth ───────────────────────────────────────────────────────────────────────

class GoogleAuthRequest(BaseModel):
    code: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshTokenRequest(BaseModel):
    refresh_token: str


# ─── User ───────────────────────────────────────────────────────────────────────

class UserOut(BaseModel):
    id: str
    name: str
    email: str
    image: str | None = None

    model_config = {"from_attributes": True}


class UserBrief(BaseModel):
    id: str
    name: str | None = None
    image: str | None = None

    model_config = {"from_attributes": True}


# ─── Video ──────────────────────────────────────────────────────────────────────

class VideoUploadUrlResponse(BaseModel):
    video_id: str
    upload_url: str
    access_key: str


class ThumbnailUploadUrlResponse(BaseModel):
    upload_url: str
    cdn_url: str
    access_key: str


class SaveVideoRequest(BaseModel):
    video_id: str = Field(..., alias="videoId", min_length=1)
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=5000)
    thumbnail_url: str = Field(..., alias="thumbnailUrl")
    visibility: str = Field(default="public", pattern=r"^(public|private)$")
    duration: int | None = None

    model_config = {"populate_by_name": True}

    @field_validator("video_id", mode="before")
    @classmethod
    def video_id_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("video_id must not be empty")
        return v


class VideoOut(BaseModel):
    id: UUID
    video_id: str
    title: str
    description: str
    video_url: str
    thumbnail_url: str
    visibility: str
    user_id: str
    views: int
    duration: int | None = None
    password_protected: bool = False
    embed_enabled: bool = True
    processing_status: str = "ready"
    processing_progress: int = 100
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class VideoWithUser(BaseModel):
    video: VideoOut
    user: UserBrief | None = None
    # When the video has a password and the request hasn't unlocked it,
    # the API strips sensitive URLs and sets this flag.
    locked: bool = False


class SetVideoPasswordRequest(BaseModel):
    # Empty string / None clears the password
    password: str | None = Field(default=None, max_length=200)


class VerifyVideoPasswordRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=200)


class VerifyVideoPasswordResponse(BaseModel):
    unlock_token: str
    expires_in: int


class EmbedSettingsRequest(BaseModel):
    embed_enabled: bool


class EmbedCodeResponse(BaseModel):
    iframe_html: str
    embed_url: str


class CommentCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=2000)
    timestamp_seconds: int | None = Field(default=None, ge=0, le=60 * 60 * 24)


class CommentUser(BaseModel):
    id: str
    name: str | None = None
    image: str | None = None

    model_config = {"from_attributes": True}


class CommentOut(BaseModel):
    id: UUID
    body: str
    timestamp_seconds: int | None = None
    created_at: datetime
    user: CommentUser | None = None

    model_config = {"from_attributes": True}


class CommentListResponse(BaseModel):
    comments: list[CommentOut]
    count: int


class PaginationMeta(BaseModel):
    current_page: int
    total_pages: int
    total_videos: int
    page_size: int


class VideoListResponse(BaseModel):
    videos: list[VideoWithUser]
    pagination: PaginationMeta


class UpdateVisibilityRequest(BaseModel):
    visibility: str = Field(..., pattern=r"^(public|private)$")


class VideoProcessingStatus(BaseModel):
    is_processed: bool
    encoding_progress: int
    status: int


class UserWithVideosResponse(BaseModel):
    user: UserOut
    videos: list[VideoWithUser]
    count: int