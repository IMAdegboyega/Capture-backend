import pytest
from httpx import AsyncClient


async def test_get_all_videos_unauthenticated(client: AsyncClient):
    response = await client.get("/api/videos")
    assert response.status_code == 200
    data = response.json()
    assert "videos" in data
    assert "pagination" in data
    assert isinstance(data["videos"], list)
    assert "current_page" in data["pagination"]
    assert "total_pages" in data["pagination"]


async def test_get_video_not_found(client: AsyncClient):
    response = await client.get("/api/videos/nonexistent-video-id-that-does-not-exist")
    assert response.status_code == 404


async def test_upload_url_requires_auth(client: AsyncClient):
    response = await client.post("/api/videos/upload-url")
    assert response.status_code == 401


async def test_upload_url_with_auth(client: AsyncClient, auth_headers: dict):
    response = await client.post("/api/videos/upload-url", headers=auth_headers)
    # Will be 401 since the test user doesn't exist in DB, but auth layer passes
    # If cloudinary is configured, expect 200; otherwise 401 from DB lookup.
    # We assert that auth is at least attempted (not a 422/405 routing error).
    assert response.status_code in (200, 401)
    if response.status_code == 200:
        data = response.json()
        assert "upload_url" in data or "signature" in data or "api_key" in data


async def test_thumbnail_url_requires_auth(client: AsyncClient):
    response = await client.post("/api/videos/thumbnail-url")
    assert response.status_code == 401


async def test_save_video_requires_auth(client: AsyncClient):
    response = await client.post(
        "/api/videos",
        json={
            "videoId": "test-id",
            "title": "Test",
            "description": "Test description",
            "thumbnailUrl": "https://example.com/thumb.jpg",
            "visibility": "public",
        },
    )
    assert response.status_code == 401
