import asyncio
import hashlib
import time

import cloudinary
import cloudinary.api
import cloudinary.uploader
import httpx

from app.config import get_settings

settings = get_settings()

# Initialize Cloudinary SDK
cloudinary.config(
    cloud_name=settings.CLOUDINARY_CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET,
    secure=True,
)


class CloudinaryService:
    """Handles all interactions with Cloudinary APIs for video + thumbnail management."""

    def __init__(self):
        self.cloud_name = settings.CLOUDINARY_CLOUD_NAME
        self.api_key = settings.CLOUDINARY_API_KEY
        self.api_secret = settings.CLOUDINARY_API_SECRET

    # ── Upload signature generation ─────────────────────────────────────────

    def generate_upload_signature(self, params_to_sign: dict) -> dict:
        """
        Generate a signed upload payload for direct client-side uploads.
        The client will POST to https://api.cloudinary.com/v1_1/{cloud}/{resource_type}/upload
        """
        timestamp = params_to_sign.get("timestamp", int(time.time()))
        params = {**params_to_sign, "timestamp": timestamp}

        # Build the string to sign: sorted key=value pairs joined with &, then append api_secret
        sorted_params = "&".join(
            f"{k}={v}" for k, v in sorted(params.items()) if v is not None
        )
        to_sign = sorted_params + self.api_secret
        signature = hashlib.sha1(to_sign.encode("utf-8")).hexdigest()

        return {
            "signature": signature,
            "timestamp": timestamp,
            "api_key": self.api_key,
            "cloud_name": self.cloud_name,
        }

    def get_video_upload_params(self, folder: str = "capture/videos") -> dict:
        """
        Return everything the client needs to upload a video directly to Cloudinary.
        """
        params_to_sign = {
            "folder": folder,
            "timestamp": int(time.time()),
        }

        sign_data = self.generate_upload_signature(params_to_sign)

        return {
            "upload_url": f"https://api.cloudinary.com/v1_1/{self.cloud_name}/video/upload",
            "signature": sign_data["signature"],
            "timestamp": sign_data["timestamp"],
            "api_key": sign_data["api_key"],
            "cloud_name": sign_data["cloud_name"],
            "folder": folder,
        }

    def get_thumbnail_upload_params(self, folder: str = "capture/thumbnails") -> dict:
        """
        Return everything the client needs to upload a thumbnail directly to Cloudinary.
        """
        params_to_sign = {
            "folder": folder,
            "timestamp": int(time.time()),
        }

        sign_data = self.generate_upload_signature(params_to_sign)

        return {
            "upload_url": f"https://api.cloudinary.com/v1_1/{self.cloud_name}/image/upload",
            "signature": sign_data["signature"],
            "timestamp": sign_data["timestamp"],
            "api_key": sign_data["api_key"],
            "cloud_name": sign_data["cloud_name"],
            "folder": folder,
        }

    # ── Video operations ────────────────────────────────────────────────────

    async def delete_video(self, public_id: str):
        """Delete a video from Cloudinary by its public_id."""
        await asyncio.to_thread(cloudinary.uploader.destroy, public_id, resource_type="video")

    async def delete_image(self, public_id: str):
        """Delete a thumbnail/image from Cloudinary by its public_id."""
        await asyncio.to_thread(cloudinary.uploader.destroy, public_id, resource_type="image")

    async def get_processing_status(self, public_id: str) -> dict:
        """Check if a video has been processed/is ready for playback."""
        try:
            result = await asyncio.to_thread(cloudinary.api.resource, public_id, resource_type="video")
            status = result.get("status", "unknown")
            print(
                f"[cloudinary.get_processing_status] public_id={public_id!r} "
                f"status={status!r} bytes={result.get('bytes')} "
                f"duration={result.get('duration')}"
            )
            # Cloudinary marks plain uploads as "active" once they exist. Some
            # accounts/pipelines report "complete" or the field may be absent
            # entirely — in that case the mere fact that .resource() succeeded
            # is enough to consider the asset playable.
            is_ready = status in {"active", "complete", "unknown"}
            return {
                "is_processed": is_ready,
                "encoding_progress": 100 if is_ready else 0,
                "status": 4 if is_ready else 0,
            }
        except Exception as e:
            # Don't swallow silently — this was masking stuck-processing bugs.
            print(
                f"[cloudinary.get_processing_status] ERROR for "
                f"public_id={public_id!r}: {type(e).__name__}: {e}"
            )
            return {
                "is_processed": False,
                "encoding_progress": 0,
                "status": 0,
            }

    async def get_transcript(self, public_id: str) -> str:
        """
        Fetch the auto-generated transcript (VTT format).
        Cloudinary stores transcripts as .transcript raw files with same public_id.
        """
        transcript_url = (
            f"https://res.cloudinary.com/{self.cloud_name}"
            f"/raw/upload/{public_id}.transcript"
        )
        async with httpx.AsyncClient() as client:
            resp = await client.get(transcript_url)
            if resp.status_code == 200:
                return resp.text
        return ""

    # ── Webhooks ────────────────────────────────────────────────────────────

    def verify_notification_signature(
        self, body: str, timestamp: str, signature: str
    ) -> bool:
        """
        Cloudinary signs webhook notifications as:
            sha1(body + timestamp + api_secret)
        sent via the X-Cld-Signature / X-Cld-Timestamp headers.
        Returns True if the signature matches.
        See https://cloudinary.com/documentation/notifications#verifying_notification_signatures
        """
        if not signature or not timestamp:
            return False
        to_sign = f"{body}{timestamp}{self.api_secret}"
        expected = hashlib.sha1(to_sign.encode("utf-8")).hexdigest()
        # Constant-time compare
        if len(expected) != len(signature):
            return False
        result = 0
        for a, b in zip(expected, signature):
            result |= ord(a) ^ ord(b)
        return result == 0

    # ── URL builders ────────────────────────────────────────────────────────

    def build_embed_url(self, public_id: str) -> str:
        """Build a Cloudinary Video Player iframe embed URL."""
        return (
            f"https://player.cloudinary.com/embed/"
            f"?cloud_name={self.cloud_name}"
            f"&public_id={public_id}"
            f"&fluid=true&controls=true"
            f"&source[source_types][0]=mp4"
        )

    def build_video_url(self, public_id: str) -> str:
        """Build a direct video delivery URL."""
        return f"https://res.cloudinary.com/{self.cloud_name}/video/upload/{public_id}"

    def build_thumbnail_url(self, public_id: str) -> str:
        """Build a thumbnail URL from a video (auto-generated)."""
        return f"https://res.cloudinary.com/{self.cloud_name}/video/upload/{public_id}.jpg"


# Singleton
cloudinary_service = CloudinaryService()