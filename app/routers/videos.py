import math
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.rate_limit import limiter
from app.models import User, Video
from app.schemas import (
    SaveVideoRequest,
    UpdateVisibilityRequest,
    UserOut,
    UserWithVideosResponse,
    VideoListResponse,
    VideoOut,
    VideoProcessingStatus,
    VideoWithUser,
    PaginationMeta,
    UserBrief,
)
from app.services.auth import get_current_user, get_optional_user
from app.services.cloudinary import cloudinary_service

router = APIRouter(prefix="/videos", tags=["Videos"])


# ─── Helpers ────────────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    return re.sub(r"[-. ]", "", text).lower()


def _title_matches(search_query: str):
    normalized = _normalize(search_query)
    return func.lower(
        func.replace(func.replace(func.replace(Video.title, "-", ""), ".", ""), " ", "")
    ).ilike(f"%{normalized}%")


def _order_clause(sort_filter: str | None):
    mapping = {
        "Most Viewed": Video.views.desc(),
        "Least Viewed": Video.views.asc(),
        "Oldest First": Video.created_at.asc(),
    }
    return mapping.get(sort_filter, Video.created_at.desc()) if sort_filter else Video.created_at.desc()


def _video_with_user(video: Video, user: User | None) -> VideoWithUser:
    return VideoWithUser(
        video=VideoOut.model_validate(video),
        user=UserBrief.model_validate(user) if user else None,
    )


# ─── Upload flow ────────────────────────────────────────────────────────────────

@router.post("/upload-url")
async def get_video_upload_url(current_user: User = Depends(get_current_user)):
    """
    Return signed upload parameters for direct client-side video upload to Cloudinary.
    """
    params = cloudinary_service.get_video_upload_params()
    return params


@router.post("/thumbnail-url")
async def get_thumbnail_upload_url(
    current_user: User = Depends(get_current_user),
):
    """Return signed upload parameters for direct client-side thumbnail upload to Cloudinary."""
    params = cloudinary_service.get_thumbnail_upload_params()
    return params


@router.post("", status_code=status.HTTP_201_CREATED)
@limiter.limit("2/minute")
async def save_video(
    request: Request,
    body: SaveVideoRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Save video details to the database after the client has uploaded
    the file and thumbnail directly to Cloudinary.
    """
    now = datetime.utcnow()
    video = Video(
        title=body.title,
        description=body.description,
        video_id=body.video_id,
        video_url=cloudinary_service.build_embed_url(body.video_id),
        thumbnail_url=body.thumbnail_url,
        visibility=body.visibility,
        duration=body.duration,
        user_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(video)
    await db.flush()

    return {"video_id": body.video_id}


# ─── List / Search ──────────────────────────────────────────────────────────────

@router.get("", response_model=VideoListResponse)
async def get_all_videos(
    query: str = "",
    filter: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(8, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    if current_user:
        visibility_filter = or_(
            Video.visibility == "public",
            Video.user_id == current_user.id,
        )
    else:
        visibility_filter = Video.visibility == "public"

    conditions = [visibility_filter]
    if query.strip():
        conditions.append(_title_matches(query))

    where = and_(*conditions)

    count_result = await db.execute(select(func.count()).select_from(Video).where(where))
    total_videos = count_result.scalar() or 0
    total_pages = math.ceil(total_videos / page_size)

    stmt = (
        select(Video, User)
        .outerjoin(User, Video.user_id == User.id)
        .where(where)
        .order_by(_order_clause(filter))
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    result = await db.execute(stmt)
    rows = result.all()

    return VideoListResponse(
        videos=[_video_with_user(v, u) for v, u in rows],
        pagination=PaginationMeta(
            current_page=page,
            total_pages=total_pages,
            total_videos=total_videos,
            page_size=page_size,
        ),
    )


# ─── User videos ─────────────────────────────────────────────────────────────────
# IMPORTANT: must be registered before /{video_id:path} or it will be shadowed.

@router.get("/user/{user_id}", response_model=UserWithVideosResponse)
async def get_user_videos(
    user_id: str,
    query: str = "",
    filter: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    is_owner = current_user and current_user.id == user_id

    conditions = [Video.user_id == user_id]
    if not is_owner:
        conditions.append(Video.visibility == "public")
    if query.strip():
        conditions.append(Video.title.ilike(f"%{query}%"))

    stmt = (
        select(Video, User)
        .outerjoin(User, Video.user_id == User.id)
        .where(and_(*conditions))
        .order_by(_order_clause(filter))
    )
    result = await db.execute(stmt)
    rows = result.all()

    return UserWithVideosResponse(
        user=UserOut.model_validate(user),
        videos=[_video_with_user(v, u) for v, u in rows],
        count=len(rows),
    )


# ─── Single video ───────────────────────────────────────────────────────────────

@router.get("/{video_id:path}", response_model=VideoWithUser)
async def get_video(video_id: str, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Video, User)
        .outerjoin(User, Video.user_id == User.id)
        .where(Video.video_id == video_id)
    )
    result = await db.execute(stmt)
    row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="Video not found")

    return _video_with_user(row[0], row[1])


@router.get("/{video_id:path}/transcript")
async def get_transcript(video_id: str):
    transcript = await cloudinary_service.get_transcript(video_id)
    return {"transcript": transcript}


@router.get("/{video_id:path}/status", response_model=VideoProcessingStatus)
async def get_processing_status(
    video_id: str,
    current_user: User = Depends(get_current_user),
):
    result = await cloudinary_service.get_processing_status(video_id)
    return VideoProcessingStatus(**result)


# ─── Video mutations ────────────────────────────────────────────────────────────

@router.patch("/{video_id:path}/views")
async def increment_views(video_id: str, db: AsyncSession = Depends(get_db)):
    stmt = select(Video).where(Video.video_id == video_id)
    result = await db.execute(stmt)
    video = result.scalar_one_or_none()

    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    video.views += 1
    video.updated_at = datetime.utcnow()

    return {"views": video.views}


@router.patch("/{video_id:path}/visibility")
@limiter.limit("2/minute")
async def update_visibility(
    request: Request,
    video_id: str,
    body: UpdateVisibilityRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Video).where(Video.video_id == video_id)
    result = await db.execute(stmt)
    video = result.scalar_one_or_none()

    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    if video.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    video.visibility = body.visibility
    video.updated_at = datetime.utcnow()

    return {"visibility": video.visibility}


@router.delete("/{video_id:path}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_video(
    video_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Video).where(Video.video_id == video_id)
    result = await db.execute(stmt)
    video = result.scalar_one_or_none()

    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    if video.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Delete video from Cloudinary
    await cloudinary_service.delete_video(video_id)

    # Delete from DB
    await db.delete(video)
