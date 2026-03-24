"""YouTube Data API v3 upload service."""

import json
import logging
from pathlib import Path

from prolific.core.config import settings

logger = logging.getLogger(__name__)


class YouTubeUploadService:
    def __init__(self, credentials_path: str | None = None):
        self.credentials_path = credentials_path or settings.youtube_credentials_path

    def _get_authenticated_service(self):
        """Build authenticated YouTube API service."""
        import base64
        import os
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds_data = None
        env_key = os.environ.get("YOUTUBE_CREDENTIALS_B64") if self.credentials_path == settings.youtube_credentials_path else None
        shorts_env_key = os.environ.get("SHORTS_CREDENTIALS_B64") if "shorts" in str(self.credentials_path) or self.credentials_path == getattr(settings, "shorts_credentials_path", "") else None

        if shorts_env_key:
            creds_data = json.loads(base64.b64decode(shorts_env_key))
        elif env_key:
            creds_data = json.loads(base64.b64decode(env_key))
        elif Path(self.credentials_path).exists():
            creds_data = json.loads(Path(self.credentials_path).read_text())
        else:
            raise FileNotFoundError(f"No credentials at {self.credentials_path} and no *_CREDENTIALS_B64 env var set")

        credentials = Credentials(
            token=creds_data.get("token"),
            refresh_token=creds_data.get("refresh_token"),
            token_uri=creds_data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=creds_data.get("client_id"),
            client_secret=creds_data.get("client_secret"),
        )
        return build("youtube", "v3", credentials=credentials)

    async def upload_video(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list[str],
        category_id: str = "27",
        privacy_status: str = "unlisted",
        thumbnail_path: str | None = None,
    ) -> dict:
        """Upload video to YouTube.

        Returns dict with video_id and url.
        """
        import asyncio
        from googleapiclient.http import MediaFileUpload

        youtube = self._get_authenticated_service()

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": category_id,
                "defaultLanguage": "en",
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False,
                "embeddable": True,
            },
        }

        media = MediaFileUpload(
            video_path,
            chunksize=50 * 1024 * 1024,
            resumable=True,
            mimetype="video/mp4",
        )

        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, self._execute_upload, request)

        video_id = response["id"]
        video_url = f"https://www.youtube.com/watch?v={video_id}"

        logger.info(f"Video uploaded: {video_url}")

        if thumbnail_path and Path(thumbnail_path).exists():
            try:
                thumb_media = MediaFileUpload(thumbnail_path, mimetype="image/png")
                thumb_request = youtube.thumbnails().set(
                    videoId=video_id,
                    media_body=thumb_media,
                )
                await loop.run_in_executor(None, thumb_request.execute)
                logger.info(f"Thumbnail set for {video_id}")
            except Exception as e:
                logger.warning(f"Failed to set thumbnail: {e}")

        return {"video_id": video_id, "url": video_url}

    async def post_comment(self, video_id: str, comment_text: str) -> str | None:
        """Post a comment on a video. Returns comment ID or None."""
        import asyncio
        try:
            youtube = self._get_authenticated_service()
            body = {
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {
                            "textOriginal": comment_text,
                        }
                    },
                },
            }
            request = youtube.commentThreads().insert(
                part="snippet",
                body=body,
            )
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, request.execute)
            comment_id = response["id"]
            logger.info(f"Posted comment on {video_id}: {comment_text[:50]}...")
            return comment_id
        except Exception as e:
            logger.warning(f"Failed to post comment on {video_id}: {e}")
            return None

    @staticmethod
    def _execute_upload(request):
        """Execute resumable upload with progress logging and retry."""
        import time
        response = None
        retries = 0
        max_retries = 5
        while response is None:
            try:
                status, response = request.next_chunk(num_retries=3)
                if status:
                    progress = int(status.progress() * 100)
                    logger.info(f"  Upload progress: {progress}%")
                retries = 0
            except Exception as e:
                retries += 1
                if retries > max_retries:
                    raise
                wait = min(2 ** retries, 60)
                logger.warning(f"  Upload chunk failed ({retries}/{max_retries}), retrying in {wait}s: {e}")
                time.sleep(wait)
        return response


_youtube_service: YouTubeUploadService | None = None


def get_youtube_upload_service() -> YouTubeUploadService:
    global _youtube_service
    if _youtube_service is None:
        _youtube_service = YouTubeUploadService()
    return _youtube_service
