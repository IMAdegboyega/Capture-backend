import pytest
import uuid
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.database as db_module
from app.config import get_settings
from app.database import get_db
from app.main import app
from app.services.auth import create_access_token


# ─── Test DB engine ──────────────────────────────────────────────────────────
#
# We swap in a NullPool engine for tests. The default pooled engine keeps
# asyncpg connections alive across tests — on Windows/Python 3.13 that leaks
# "Event loop is closed" and "another operation is in progress" errors
# because each test runs in a fresh event loop. NullPool opens and closes
# a connection per request, which plays nicely with per-test loops.

_settings = get_settings()
_test_db_url = _settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)


@pytest.fixture(scope="session")
def test_engine():
    engine = create_async_engine(
        _test_db_url,
        poolclass=NullPool,
        connect_args={"statement_cache_size": 0},
    )
    yield engine


@pytest.fixture
async def _override_db(test_engine):
    """Override the get_db dependency so every request gets a fresh connection."""
    session_maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def _get_db_override():
        async with session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    app.dependency_overrides[get_db] = _get_db_override
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def test_user_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def access_token(test_user_id: str) -> str:
    return create_access_token(test_user_id)


@pytest.fixture
def auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
async def client(_override_db) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
