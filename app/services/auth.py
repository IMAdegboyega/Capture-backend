import uuid
from datetime import datetime, timedelta, timezone

import httpx
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import Account, Session, User

settings = get_settings()
security = HTTPBearer(auto_error=False)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


# ─── Token creation ──────────────────────────────────────────────────────────

def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": user_id, "exp": expire, "type": "access"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": user_id, "exp": expire, "type": "refresh"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


# ─── Google OAuth ─────────────────────────────────────────────────────────────

async def exchange_google_code(code: str) -> dict:
    """Exchange the authorization code for Google tokens and fetch user info."""
    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to exchange Google auth code",
            )
        tokens = token_resp.json()

        # Fetch user info
        userinfo_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        if userinfo_resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to fetch Google user info",
            )

    return {**userinfo_resp.json(), "google_tokens": tokens}


async def get_or_create_user(db: AsyncSession, google_data: dict) -> User:
    """Find existing user by Google account or create a new one."""
    google_id = str(google_data["id"])

    # Check if account already linked
    result = await db.execute(
        select(Account).where(
            Account.provider_id == "google",
            Account.account_id == google_id,
        )
    )
    account = result.scalar_one_or_none()

    if account:
        user_result = await db.execute(select(User).where(User.id == account.user_id))
        return user_result.scalar_one()

    # Check if user exists by email
    result = await db.execute(
        select(User).where(User.email == google_data["email"])
    )
    user = result.scalar_one_or_none()

    now = datetime.utcnow()

    if not user:
        user = User(
            id=str(uuid.uuid4()),
            name=google_data.get("name", ""),
            email=google_data["email"],
            email_verified=google_data.get("verified_email", False),
            image=google_data.get("picture"),
            created_at=now,
            updated_at=now,
        )
        db.add(user)
        await db.flush()

    # Link Google account
    google_tokens = google_data.get("google_tokens", {})
    account = Account(
        id=str(uuid.uuid4()),
        account_id=google_id,
        provider_id="google",
        user_id=user.id,
        access_token=google_tokens.get("access_token"),
        refresh_token=google_tokens.get("refresh_token"),
        id_token=google_tokens.get("id_token"),
        scope=google_tokens.get("scope"),
        created_at=now,
        updated_at=now,
    )
    db.add(account)

    return user


async def create_session_record(
    db: AsyncSession, user_id: str, token: str, ip: str | None, ua: str | None
) -> Session:
    """Persist a session row (mirrors the better-auth session table)."""
    now = datetime.utcnow()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=user_id,
        token=token,
        expires_at=now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        ip_address=ip,
        user_agent=ua,
        created_at=now,
        updated_at=now,
    )
    db.add(session)
    return session


# ─── Dependency: get current user ────────────────────────────────────────────

async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """FastAPI dependency — extracts & validates JWT, returns the User row."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    payload = decode_token(credentials.credentials)
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Same as get_current_user but returns None instead of raising for unauthenticated."""
    if credentials is None:
        return None
    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None
