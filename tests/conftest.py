import pytest
import uuid
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.services.auth import create_access_token


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
async def client() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
