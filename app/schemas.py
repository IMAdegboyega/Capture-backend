from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


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
    video_id: str = Field(..., alias="videoId")
    title: str
    description: str
    thumbnail_url: str = Field(..., alias="thumbnailUrl")
    visibility: str = "public"
    duration: int | None = None

    model_config = {"populate_by_name": True}


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
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class VideoWithUser(BaseModel):
    video: VideoOut
    user: UserBrief | None = None


class PaginationMeta(BaseModel):
    current_page: int
    total_pages: int
    total_videos: int
    page_size: int


class VideoListResponse(BaseModel):
    videos: list[VideoWithUser]
    pagination: PaginationMeta


class UpdateVisibilityRequest(BaseModel):
    visibility: str


class VideoProcessingStatus(BaseModel):
    is_processed: bool
    encoding_progress: int
    status: int


class UserWithVideosResponse(BaseModel):
    user: UserOut
    videos: list[VideoWithUser]
    count: int
