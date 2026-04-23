"""
Smoke tests for the new features. These don't require a reachable DB —
they verify authentication routing, Pydantic validation, password hashing,
video-unlock JWT roundtrips, and Cloudinary webhook signature logic.

Tests that inherently need a database (e.g. creating a Video row to
password-protect) live in integration-style suites, not here.
"""
import hashlib
import json
import uuid

from httpx import AsyncClient

from app.services.auth import (
    create_video_unlock_token,
    hash_password,
    verify_password,
    verify_video_unlock_token,
)
from app.services.cloudinary import cloudinary_service


# ─── Comments — auth routing ─────────────────────────────────────────────────

async def test_comments_create_requires_auth(client: AsyncClient):
    response = await client.post(
        "/api/videos/some-video-id/comments",
        json={"body": "hello"},
    )
    assert response.status_code == 401


async def test_comments_delete_requires_auth(client: AsyncClient):
    response = await client.delete(
        f"/api/videos/some-video-id/comments/{uuid.uuid4()}",
    )
    assert response.status_code == 401


# ─── Password protection — auth + validation routing ────────────────────────

async def test_set_password_requires_auth(client: AsyncClient):
    response = await client.patch(
        "/api/videos/some-video-id/password",
        json={"password": "hunter2"},
    )
    assert response.status_code == 401


async def test_verify_password_rejects_empty(client: AsyncClient):
    response = await client.post(
        "/api/videos/some-video-id/verify-password",
        json={"password": ""},
    )
    # Pydantic min_length=1 catches this before any DB call
    assert response.status_code == 422


async def test_embed_patch_requires_auth(client: AsyncClient):
    response = await client.patch(
        "/api/videos/some-video-id/embed",
        json={"embed_enabled": False},
    )
    assert response.status_code == 401


# ─── Password hashing primitives ─────────────────────────────────────────────

def test_password_hash_roundtrip():
    hashed = hash_password("hunter2")
    assert hashed != "hunter2"
    assert verify_password("hunter2", hashed)
    assert not verify_password("wrong", hashed)


def test_video_unlock_token_roundtrip():
    token, expires_in = create_video_unlock_token("abc")
    assert expires_in > 0
    assert verify_video_unlock_token(token, "abc") is True
    # Wrong video_id must fail
    assert verify_video_unlock_token(token, "xyz") is False
    # Garbage token must fail
    assert verify_video_unlock_token("not.a.jwt", "abc") is False
    # Missing token must fail
    assert verify_video_unlock_token(None, "abc") is False


# ─── Cloudinary webhook signature logic ──────────────────────────────────────

def test_cloudinary_signature_verification():
    body = '{"public_id": "abc", "status": "active"}'
    timestamp = "1712345678"
    to_sign = f"{body}{timestamp}{cloudinary_service.api_secret}"
    sig = hashlib.sha1(to_sign.encode("utf-8")).hexdigest()

    assert cloudinary_service.verify_notification_signature(body, timestamp, sig)
    # Wrong sig must fail
    assert not cloudinary_service.verify_notification_signature(
        body, timestamp, "deadbeef" * 5
    )
    # Missing pieces must fail
    assert not cloudinary_service.verify_notification_signature(body, "", sig)
    assert not cloudinary_service.verify_notification_signature(body, timestamp, "")


async def test_cloudinary_webhook_rejects_bad_signature(client: AsyncClient):
    payload = {"public_id": "whatever", "status": "active"}
    response = await client.post(
        "/api/videos/webhook/cloudinary",
        json=payload,
        headers={
            "X-Cld-Signature": "clearly-wrong",
            "X-Cld-Timestamp": "1712345678",
        },
    )
    assert response.status_code == 401


async def test_cloudinary_webhook_rejects_missing_headers(client: AsyncClient):
    # No signature headers at all
    response = await client.post(
        "/api/videos/webhook/cloudinary",
        json={"public_id": "abc", "status": "active"},
    )
    assert response.status_code == 401
