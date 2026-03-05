from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.middleware.rate_limit import limiter
from app.schemas import GoogleAuthRequest, RefreshTokenRequest, TokenResponse, UserOut
from app.services.auth import (
    create_access_token,
    create_refresh_token,
    create_session_record,
    decode_token,
    exchange_google_code,
    get_current_user,
    get_or_create_user,
)
from app.models import User

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/google", response_model=TokenResponse)
@limiter.limit("5/minute")
async def google_login(
    request: Request,
    body: GoogleAuthRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Exchange a Google authorization code for app JWT tokens.
    Creates or links the user account on first login.
    """
    google_data = await exchange_google_code(body.code)
    user = await get_or_create_user(db, google_data)

    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)

    await create_session_record(
        db,
        user_id=user.id,
        token=access_token,
        ip=request.client.host if request.client else None,
        ua=request.headers.get("user-agent"),
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("10/minute")
async def refresh_token(request: Request, body: RefreshTokenRequest):
    """Issue a new access token using a valid refresh token."""
    payload = decode_token(body.refresh_token)
    if payload.get("type") != "refresh":
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    user_id = payload["sub"]
    new_access = create_access_token(user_id)
    new_refresh = create_refresh_token(user_id)

    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    """Return the authenticated user's profile."""
    return current_user
