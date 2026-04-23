import math
import re
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.rate_limit import limiter
from app.models import Comment, User, Video
from app.schemas import (
    CommentCreate,
    CommentListResponse,
    CommentOut,
    CommentUser,
    EmbedCodeResponse,
    EmbedSettingsRequest,
    SaveVideoRequest,
    SetVideoPasswordRequest,
    UpdateVisibilityRequest,
    UserOut,
    UserWithVideosResponse,
    VerifyVideoPasswordRequest,
    VerifyVideoPasswordResponse,
    VideoListResponse,
    VideoOut,
    VideoProcessingStatus,
    VideoWithUser,
    PaginationMeta,
    UserBrief,
)
from app.services.auth import (
    create_video_unlock_token,
    get_current_user,
    get_optional_user,
    hash_password,
    verify_password,
    verify_video_unlock_token,
)
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


def _video_out(video: Video) -> VideoOut:
    """Build a VideoOut, derived flags included, password_hash omitted."""
    return VideoOut(
        id=video.id,
        video_id=video.video_id,
        title=video.title,
        description=video.description,
        video_url=video.video_url,
        thumbnail_url=video.thumbnail_url,
        visibility=video.visibility,
        user_id=video.user_id,
        views=video.views,
        duration=video.duration,
        password_protected=bool(video.password_hash),
        embed_enabled=bool(video.embed_enabled),
        processing_status=video.processing_status or "ready",
        processing_progress=video.processing_progress or 100,
        created_at=video.created_at,
        updated_at=video.updated_at,
    )


def _video_with_user(
    video: Video, user: User | None, *, locked: bool = False
) -> VideoWithUser:
    out = _video_out(video)
    if locked:
        # Strip the playback URLs so a locked viewer can't just hit Cloudinary directly.
        out = out.model_copy(update={"video_url": "", "thumbnail_url": out.thumbnail_url})
    return VideoWithUser(
        video=out,
        user=UserBrief.model_validate(user) if user else None,
        locked=locked,
    )


async def _get_video_or_404(db: AsyncSession, video_id: str) -> Video:
    stmt = select(Video).where(Video.video_id == video_id)
    result = await db.execute(stmt)
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return video


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
        # New uploads start as "processing"; webhook will flip to "ready".
        processing_status="processing",
        processing_progress=0,
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


# ─── Cloudinary webhook (PUBLIC) ────────────────────────────────────────────────
# Must be registered before the /{video_id:path} catch-all below.

@router.post("/webhook/cloudinary", include_in_schema=True)
async def cloudinary_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_cld_signature: str | None = Header(default=None, alias="X-Cld-Signature"),
    x_cld_timestamp: str | None = Header(default=None, alias="X-Cld-Timestamp"),
):
    """
    Receives Cloudinary notifications (e.g. upload / eager completion) and
    updates the corresponding Video row's processing_status. Signature
    verified against CLOUDINARY_API_SECRET.
    """
    raw_body = (await request.body()).decode("utf-8")
    if not cloudinary_service.verify_notification_signature(
        raw_body, x_cld_timestamp or "", x_cld_signature or ""
    ):
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()
    public_id = payload.get("public_id")
    cld_status = payload.get("status", "")
    notification_type = payload.get("notification_type", "")

    if not public_id:
        return {"ok": True, "skipped": "no public_id"}

    video = (
        await db.execute(select(Video).where(Video.video_id == public_id))
    ).scalar_one_or_none()
    if not video:
        # Unknown asset — return 200 so Cloudinary stops retrying.
        return {"ok": True, "skipped": "unknown video"}

    if cld_status == "active" or notification_type in {"upload", "eager"}:
        video.processing_status = "ready"
        video.processing_progress = 100
    elif cld_status == "failed" or notification_type == "error":
        video.processing_status = "failed"
    else:
        video.processing_status = "processing"

    video.updated_at = datetime.utcnow()
    return {"ok": True, "video_id": public_id, "status": video.processing_status}


# NOTE: The single-video `GET /{video_id:path}` route is registered at the
# bottom of this file, AFTER every `/{video_id:path}/<suffix>` route. The
# `:path` converter is greedy, so registering it earlier would shadow
# /status, /transcript, /comments, /embed and make them all return 404.


@router.get("/{video_id:path}/transcript")
async def get_transcript(
    video_id: str,
    db: AsyncSession = Depends(get_db),
    x_video_unlock: str | None = Header(default=None, alias="X-Video-Unlock"),
    current_user: User | None = Depends(get_optional_user),
):
    # Gate transcript behind password too.
    video = await _get_video_or_404(db, video_id)
    if video.password_hash:
        is_owner = current_user and current_user.id == video.user_id
        if not is_owner and not verify_video_unlock_token(x_video_unlock, video_id):
            raise HTTPException(status_code=401, detail="Password required")

    transcript = await cloudinary_service.get_transcript(video_id)
    return {"transcript": transcript}


@router.get("/{video_id:path}/status", response_model=VideoProcessingStatus)
async def get_processing_status(
    video_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    DB-first: uses the webhook-persisted status when available so we don't
    hammer Cloudinary on every poll. Falls back to a live Cloudinary check
    only when the DB says the video is still processing.
    """
    video = await _get_video_or_404(db, video_id)
    if video.processing_status == "ready":
        return VideoProcessingStatus(
            is_processed=True, encoding_progress=100, status=4
        )
    if video.processing_status == "failed":
        return VideoProcessingStatus(
            is_processed=False, encoding_progress=0, status=0
        )
    # Still processing — optionally reconcile with Cloudinary so dev
    # environments without a public webhook URL still make progress.
    live = await cloudinary_service.get_processing_status(video_id)
    if live.get("is_processed"):
        video.processing_status = "ready"
        video.processing_progress = 100
        video.updated_at = datetime.utcnow()
    return VideoProcessingStatus(**live)


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
    video = await _get_video_or_404(db, video_id)
    if video.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    video.visibility = body.visibility
    video.updated_at = datetime.utcnow()

    return {"visibility": video.visibility}


# ─── Password protection ────────────────────────────────────────────────────────

@router.patch("/{video_id:path}/password")
@limiter.limit("5/minute")
async def set_video_password(
    request: Request,
    video_id: str,
    body: SetVideoPasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Owner sets (or clears, with empty/null) a video password."""
    video = await _get_video_or_404(db, video_id)
    if video.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    if body.password:
        video.password_hash = hash_password(body.password)
    else:
        video.password_hash = None
    video.updated_at = datetime.utcnow()

    return {"password_protected": bool(video.password_hash)}


@router.post(
    "/{video_id:path}/verify-password",
    response_model=VerifyVideoPasswordResponse,
)
@limiter.limit("10/minute")
async def verify_video_password(
    request: Request,
    video_id: str,
    body: VerifyVideoPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Viewer submits the password. Returns an unlock JWT on success."""
    video = await _get_video_or_404(db, video_id)
    if not video.password_hash:
        raise HTTPException(status_code=400, detail="Video is not password protected")
    if not verify_password(body.password, video.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect password")

    token, expires_in = create_video_unlock_token(video_id)
    return VerifyVideoPasswordResponse(unlock_token=token, expires_in=expires_in)


# ─── Embed settings ─────────────────────────────────────────────────────────────

@router.patch("/{video_id:path}/embed")
async def update_embed_settings(
    video_id: str,
    body: EmbedSettingsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    video = await _get_video_or_404(db, video_id)
    if video.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    video.embed_enabled = body.embed_enabled
    video.updated_at = datetime.utcnow()
    return {"embed_enabled": video.embed_enabled}


@router.get("/{video_id:path}/embed", response_model=EmbedCodeResponse)
async def get_embed_code(
    video_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Public endpoint returning a ready-to-paste iframe snippet.
    Disabled for password-protected videos and for owners who've opted out.
    """
    video = await _get_video_or_404(db, video_id)
    if not video.embed_enabled or video.password_hash or video.visibility != "public":
        raise HTTPException(
            status_code=403, detail="Embedding is disabled for this video"
        )
    embed_url = cloudinary_service.build_embed_url(video_id)
    iframe_html = (
        f'<iframe src="{embed_url}" width="640" height="360" '
        f'frameborder="0" allow="autoplay; fullscreen; picture-in-picture" '
        f'allowfullscreen title="{video.title}"></iframe>'
    )
    return EmbedCodeResponse(iframe_html=iframe_html, embed_url=embed_url)


# ─── Comments ───────────────────────────────────────────────────────────────────

@router.get("/{video_id:path}/comments", response_model=CommentListResponse)
async def list_comments(
    video_id: str,
    db: AsyncSession = Depends(get_db),
    x_video_unlock: str | None = Header(default=None, alias="X-Video-Unlock"),
    current_user: User | None = Depends(get_optional_user),
):
    video = await _get_video_or_404(db, video_id)
    if video.password_hash:
        is_owner = current_user and current_user.id == video.user_id
        if not is_owner and not verify_video_unlock_token(x_video_unlock, video_id):
            raise HTTPException(status_code=401, detail="Password required")

    stmt = (
        select(Comment, User)
        .outerjoin(User, Comment.user_id == User.id)
        .where(Comment.video_pk == video.id)
        .order_by(Comment.created_at.asc())
    )
    rows = (await db.execute(stmt)).all()

    comments = [
        CommentOut(
            id=c.id,
            body=c.body,
            timestamp_seconds=c.timestamp_seconds,
            created_at=c.created_at,
            user=CommentUser.model_validate(u) if u else None,
        )
        for c, u in rows
    ]
    return CommentListResponse(comments=comments, count=len(comments))


@router.post(
    "/{video_id:path}/comments",
    response_model=CommentOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("20/minute")
async def create_comment(
    request: Request,
    video_id: str,
    body: CommentCreate,
    db: AsyncSession = Depends(get_db),
    x_video_unlock: str | None = Header(default=None, alias="X-Video-Unlock"),
    current_user: User = Depends(get_current_user),
):
    video = await _get_video_or_404(db, video_id)
    if video.password_hash and video.user_id != current_user.id:
        if not verify_video_unlock_token(x_video_unlock, video_id):
            raise HTTPException(status_code=401, detail="Password required")

    now = datetime.utcnow()
    comment = Comment(
        video_pk=video.id,
        user_id=current_user.id,
        body=body.body,
        timestamp_seconds=body.timestamp_seconds,
        created_at=now,
        updated_at=now,
    )
    db.add(comment)
    await db.flush()

    return CommentOut(
        id=comment.id,
        body=comment.body,
        timestamp_seconds=comment.timestamp_seconds,
        created_at=comment.created_at,
        user=CommentUser.model_validate(current_user),
    )


@router.delete(
    "/{video_id:path}/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_comment(
    video_id: str,
    comment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    video = await _get_video_or_404(db, video_id)
    stmt = select(Comment).where(Comment.id == comment_id, Comment.video_pk == video.id)
    comment = (await db.execute(stmt)).scalar_one_or_none()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    # Only the commenter or the video owner can delete.
    if comment.user_id != current_user.id and video.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    await db.delete(comment)


# ─── Single video ───────────────────────────────────────────────────────────────
# MUST stay below every `/{video_id:path}/<suffix>` GET route above — the
# `:path` converter is greedy and would otherwise swallow them all.

@router.get("/{video_id:path}", response_model=VideoWithUser)
async def get_video(
    video_id: str,
    db: AsyncSession = Depends(get_db),
    x_video_unlock: str | None = Header(default=None, alias="X-Video-Unlock"),
    current_user: User | None = Depends(get_optional_user),
):
    stmt = (
        select(Video, User)
        .outerjoin(User, Video.user_id == User.id)
        .where(Video.video_id == video_id)
    )
    result = await db.execute(stmt)
    row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="Video not found")

    video, user = row
    # Owner bypasses password; otherwise require a valid unlock token
    locked = False
    if video.password_hash:
        is_owner = current_user and current_user.id == video.user_id
        if not is_owner and not verify_video_unlock_token(x_video_unlock, video_id):
            locked = True

    return _video_with_user(video, user, locked=locked)


# ─── Delete video ───────────────────────────────────────────────────────────────

@router.delete("/{video_id:path}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_video(
    video_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    video = await _get_video_or_404(db, video_id)
    if video.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Attempt Cloudinary cleanup — don't block DB deletion if it fails
    try:
        await cloudinary_service.delete_video(video_id)
    except Exception:
        pass  # Orphaned Cloudinary asset is acceptable; DB row must go

    # Always delete from DB
    await db.delete(video)
