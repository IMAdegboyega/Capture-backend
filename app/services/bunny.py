import httpx

from app.config import get_settings

settings = get_settings()


class BunnyService:
    """Handles all interactions with Bunny.net APIs (Stream, Storage, CDN)."""

    def __init__(self):
        self.library_id = settings.BUNNY_LIBRARY_ID
        self.stream_key = settings.BUNNY_STREAM_ACCESS_KEY
        self.storage_key = settings.BUNNY_STORAGE_ACCESS_KEY
        self.stream_base = settings.BUNNY_STREAM_BASE_URL
        self.storage_base = settings.BUNNY_STORAGE_BASE_URL
        self.cdn_url = settings.BUNNY_CDN_URL
        self.embed_url = settings.BUNNY_EMBED_URL
        self.transcript_url = settings.BUNNY_TRANSCRIPT_URL

    # ── Stream API helpers ──────────────────────────────────────────────────

    def _stream_headers(self, with_json_body: bool = False) -> dict:
        headers = {"AccessKey": self.stream_key, "accept": "application/json"}
        if with_json_body:
            headers["content-type"] = "application/json"
        return headers

    def _storage_headers(self) -> dict:
        return {"AccessKey": self.storage_key}

    # ── Video operations ────────────────────────────────────────────────────

    async def create_video_placeholder(self) -> dict:
        """Create a placeholder video in Bunny Stream and return its guid + upload URL."""
        url = f"{self.stream_base}/{self.library_id}/videos"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                headers=self._stream_headers(with_json_body=True),
                json={"title": "Temp Title", "collectionId": ""},
            )
            resp.raise_for_status()
            data = resp.json()

        video_id = data["guid"]
        upload_url = f"{self.stream_base}/{self.library_id}/videos/{video_id}"
        return {
            "video_id": video_id,
            "upload_url": upload_url,
            "access_key": self.stream_key,
        }

    async def update_video_info(self, video_id: str, title: str, description: str):
        """Update title/description on Bunny Stream."""
        url = f"{self.stream_base}/{self.library_id}/videos/{video_id}"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                headers=self._stream_headers(with_json_body=True),
                json={"title": title, "description": description},
            )
            resp.raise_for_status()

    async def delete_video(self, video_id: str):
        """Delete a video from Bunny Stream."""
        url = f"{self.stream_base}/{self.library_id}/videos/{video_id}"
        async with httpx.AsyncClient() as client:
            resp = await client.delete(url, headers=self._stream_headers())
            resp.raise_for_status()

    async def get_processing_status(self, video_id: str) -> dict:
        """Get encoding/processing status of a video."""
        url = f"{self.stream_base}/{self.library_id}/videos/{video_id}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=self._stream_headers())
            resp.raise_for_status()
            data = resp.json()

        return {
            "is_processed": data.get("status") == 4,
            "encoding_progress": data.get("encodeProgress", 0),
            "status": data.get("status", 0),
        }

    async def get_transcript(self, video_id: str) -> str:
        """Fetch auto-generated English transcript (VTT)."""
        url = f"{self.transcript_url}/{video_id}/captions/en-auto.vtt"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.text
            return ""

    # ── Thumbnail operations ────────────────────────────────────────────────

    def get_thumbnail_upload_info(self, video_id: str) -> dict:
        """Generate timestamped thumbnail upload URL + CDN URL."""
        import time

        filename = f"{int(time.time() * 1000)}-{video_id}-thumbnail"
        upload_url = f"{self.storage_base}/thumbnails/{filename}"
        cdn_url = f"{self.cdn_url}/thumbnails/{filename}"
        return {
            "upload_url": upload_url,
            "cdn_url": cdn_url,
            "access_key": self.storage_key,
        }

    async def delete_thumbnail(self, thumbnail_url: str):
        """Delete a thumbnail from Bunny Storage."""
        thumbnail_path = thumbnail_url.split("thumbnails/")[1]
        url = f"{self.storage_base}/thumbnails/{thumbnail_path}"
        async with httpx.AsyncClient() as client:
            resp = await client.delete(url, headers=self._storage_headers())
            resp.raise_for_status()

    # ── URL builders ────────────────────────────────────────────────────────

    def build_embed_url(self, video_id: str) -> str:
        return f"{self.embed_url}/{self.library_id}/{video_id}"


# Singleton
bunny_service = BunnyService()
