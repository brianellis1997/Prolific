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

    async def upload_caption_track(
        self,
        video_id: str,
        srt_path: str,
        language: str = "en",
        name: str = "English",
    ) -> str | None:
        """Upload an SRT caption track to a video.

        Uploading our own caption track tells YouTube not to render
        auto-generated CC for that language, which removes the small
        black-box caption overlay at the top of the frame that visually
        conflicts with our burned-in ASS captions at the bottom.

        Returns caption ID or None on failure (non-fatal).
        """
        import asyncio
        from googleapiclient.http import MediaFileUpload

        if not Path(srt_path).exists():
            logger.warning(f"SRT not found at {srt_path} — skipping caption upload")
            return None

        try:
            youtube = self._get_authenticated_service()
            body = {
                "snippet": {
                    "videoId": video_id,
                    "language": language,
                    "name": name,
                    "isDraft": False,
                },
            }
            media = MediaFileUpload(srt_path, mimetype="application/octet-stream", resumable=False)
            request = youtube.captions().insert(part="snippet", body=body, media_body=media)
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, request.execute)
            caption_id = response.get("id")
            logger.info(f"Uploaded caption track for {video_id} (id={caption_id}) — auto-CC suppressed")
            return caption_id
        except Exception as e:
            logger.warning(f"Caption track upload failed for {video_id} (non-fatal): {e}")
            return None

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

    async def list_comment_threads(self, video_id: str, max_results: int = 50) -> list[dict]:
        """Fetch top-level comment threads for a video."""
        import asyncio
        try:
            youtube = self._get_authenticated_service()

            def _fetch():
                response = youtube.commentThreads().list(
                    videoId=video_id,
                    part="snippet,replies",
                    maxResults=max_results,
                    order="time",
                ).execute()
                threads = []
                for item in response.get("items", []):
                    snippet = item["snippet"]["topLevelComment"]["snippet"]
                    existing_replies = []
                    if item.get("replies"):
                        for reply in item["replies"]["comments"]:
                            existing_replies.append({
                                "author": reply["snippet"]["authorDisplayName"],
                                "text": reply["snippet"]["textOriginal"],
                                "author_channel_id": reply["snippet"].get("authorChannelId", {}).get("value", ""),
                            })
                    threads.append({
                        "thread_id": item["id"],
                        "comment_id": item["snippet"]["topLevelComment"]["id"],
                        "author": snippet["authorDisplayName"],
                        "author_channel_id": snippet.get("authorChannelId", {}).get("value", ""),
                        "text": snippet["textOriginal"],
                        "published_at": snippet["publishedAt"],
                        "reply_count": item["snippet"]["totalReplyCount"],
                        "existing_replies": existing_replies,
                    })
                return threads

            return await asyncio.get_event_loop().run_in_executor(None, _fetch)
        except Exception as e:
            logger.warning(f"Failed to list comments for {video_id}: {e}")
            return []

    async def reply_to_comment(self, parent_id: str, text: str) -> str | None:
        """Reply to a comment thread. Returns reply comment ID or None."""
        import asyncio
        try:
            youtube = self._get_authenticated_service()
            body = {
                "snippet": {
                    "parentId": parent_id,
                    "textOriginal": text,
                },
            }
            request = youtube.comments().insert(part="snippet", body=body)
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, request.execute)
            reply_id = response["id"]
            logger.info(f"Replied to {parent_id}: {text[:50]}...")
            return reply_id
        except Exception as e:
            logger.warning(f"Failed to reply to {parent_id}: {e}")
            return None

    async def get_channel_id(self) -> str | None:
        """Get the authenticated channel's ID."""
        import asyncio
        try:
            youtube = self._get_authenticated_service()
            def _fetch():
                resp = youtube.channels().list(part="id", mine=True).execute()
                items = resp.get("items", [])
                return items[0]["id"] if items else None
            return await asyncio.get_event_loop().run_in_executor(None, _fetch)
        except Exception as e:
            logger.warning(f"Failed to get channel ID: {e}")
            return None

    async def get_recent_video_ids(self, max_results: int = 20) -> list[str]:
        """Get recent video IDs from the channel."""
        import asyncio
        try:
            youtube = self._get_authenticated_service()
            def _fetch():
                resp = youtube.search().list(
                    part="id", forMine=True, type="video",
                    maxResults=max_results, order="date",
                ).execute()
                return [item["id"]["videoId"] for item in resp.get("items", [])]
            return await asyncio.get_event_loop().run_in_executor(None, _fetch)
        except Exception as e:
            logger.warning(f"Failed to get recent videos: {e}")
            return []

    async def get_or_create_playlist(
        self, title: str, description: str = "", privacy_status: str = "public"
    ) -> str | None:
        """Find a playlist on this channel by exact title, or create it. Returns playlist ID.

        Idempotent: safe to call on every upload. Looks through the channel's own
        playlists first (1 quota unit); only creates (50 units) if none matches.
        Returns None on failure so the caller can skip playlist-add without failing
        the upload.
        """
        import asyncio
        try:
            youtube = self._get_authenticated_service()

            def _find_or_create():
                # Page through the channel's playlists looking for an exact title match.
                page_token = None
                while True:
                    resp = youtube.playlists().list(
                        part="id,snippet", mine=True, maxResults=50,
                        pageToken=page_token,
                    ).execute()
                    for item in resp.get("items", []):
                        if item["snippet"]["title"].strip().lower() == title.strip().lower():
                            return item["id"]
                    page_token = resp.get("nextPageToken")
                    if not page_token:
                        break
                # Not found — create it.
                created = youtube.playlists().insert(
                    part="snippet,status",
                    body={
                        "snippet": {"title": title, "description": description},
                        "status": {"privacyStatus": privacy_status},
                    },
                ).execute()
                logger.info(f"Created playlist '{title}' -> {created['id']}")
                return created["id"]

            return await asyncio.get_event_loop().run_in_executor(None, _find_or_create)
        except Exception as e:
            logger.warning(f"get_or_create_playlist('{title}') failed: {e}")
            return None

    async def add_video_to_playlist(self, playlist_id: str, video_id: str) -> bool:
        """Append a video to a playlist. Returns True on success.

        Non-fatal: logs and returns False on failure so it can't break an upload.
        """
        import asyncio
        try:
            youtube = self._get_authenticated_service()

            def _insert():
                youtube.playlistItems().insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "playlistId": playlist_id,
                            "resourceId": {"kind": "youtube#video", "videoId": video_id},
                        }
                    },
                ).execute()
                return True

            return await asyncio.get_event_loop().run_in_executor(None, _insert)
        except Exception as e:
            logger.warning(f"add_video_to_playlist({playlist_id}, {video_id}) failed: {e}")
            return False

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
