"""Web content fetching and extraction service.

Fetches URLs and extracts main content using trafilatura
for clean text extraction. Special handling for YouTube
to extract transcripts instead of parsing heavy HTML.
"""

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from dateutil import parser as date_parser
from urllib.parse import urlparse, parse_qs

import httpx
from trafilatura import extract, bare_extraction
from trafilatura.settings import use_config

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import (
        TranscriptsDisabled,
        NoTranscriptFound,
        VideoUnavailable,
    )
    YOUTUBE_TRANSCRIPT_AVAILABLE = True
except ImportError:
    YOUTUBE_TRANSCRIPT_AVAILABLE = False

logger = logging.getLogger(__name__)

trafilatura_config = use_config()
trafilatura_config.set("DEFAULT", "EXTRACTION_TIMEOUT", "30")


@dataclass
class FetchedContent:
    """Fetched and extracted web content."""

    url: str
    title: str | None
    author: str | None
    content: str
    publish_date: datetime | None
    word_count: int
    content_hash: str
    fetch_time: datetime


class WebFetchService:
    """Service for fetching and extracting web content.

    Uses trafilatura for intelligent content extraction that
    removes boilerplate and extracts main article content.
    """

    YOUTUBE_DOMAINS = {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"}

    def __init__(self, timeout: int = 30):
        """Initialize web fetch service.

        Args:
            timeout: Request timeout in seconds
        """
        self.timeout = timeout
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; ProlificBot/1.0; +https://prolific.ai)"
            },
        )
        logger.info("WebFetchService initialized")

    def _is_youtube_url(self, url: str) -> bool:
        """Check if URL is a YouTube video URL."""
        try:
            parsed = urlparse(url)
            return parsed.netloc.lower() in self.YOUTUBE_DOMAINS
        except Exception:
            return False

    def _extract_youtube_video_id(self, url: str) -> str | None:
        """Extract video ID from YouTube URL."""
        try:
            parsed = urlparse(url)
            if parsed.netloc.lower() == "youtu.be":
                return parsed.path.strip("/")
            if "youtube.com" in parsed.netloc.lower():
                if "/watch" in parsed.path:
                    query = parse_qs(parsed.query)
                    return query.get("v", [None])[0]
                elif "/shorts/" in parsed.path or "/embed/" in parsed.path:
                    parts = parsed.path.split("/")
                    for i, part in enumerate(parts):
                        if part in ("shorts", "embed") and i + 1 < len(parts):
                            return parts[i + 1]
        except Exception as e:
            logger.warning(f"Failed to extract YouTube video ID from {url}: {e}")
        return None

    async def _fetch_youtube_transcript(self, url: str) -> FetchedContent | None:
        """Fetch YouTube video transcript.

        Args:
            url: YouTube video URL

        Returns:
            FetchedContent with transcript, or None if unavailable
        """
        if not YOUTUBE_TRANSCRIPT_AVAILABLE:
            logger.warning("youtube-transcript-api not installed, skipping YouTube transcript")
            return None

        video_id = self._extract_youtube_video_id(url)
        if not video_id:
            logger.warning(f"Could not extract video ID from {url}")
            return None

        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

            transcript = None
            try:
                transcript = transcript_list.find_transcript(['en'])
            except NoTranscriptFound:
                try:
                    transcript = transcript_list.find_generated_transcript(['en'])
                except NoTranscriptFound:
                    for t in transcript_list:
                        transcript = t.translate('en')
                        break

            if not transcript:
                logger.info(f"No transcript available for YouTube video {video_id}")
                return None

            transcript_data = transcript.fetch()

            full_text = " ".join(entry["text"] for entry in transcript_data)
            full_text = re.sub(r'\s+', ' ', full_text).strip()

            video_title = f"YouTube Video {video_id}"
            try:
                response = await self._client.get(
                    f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
                )
                if response.status_code == 200:
                    oembed = response.json()
                    video_title = oembed.get("title", video_title)
                    author = oembed.get("author_name")
            except Exception:
                author = None

            content = f"[YouTube Video Transcript]\n\nTitle: {video_title}\n\n{full_text}"
            content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
            word_count = len(content.split())

            logger.info(f"Fetched YouTube transcript for {video_id}: {word_count} words")

            return FetchedContent(
                url=url,
                title=video_title,
                author=author if 'author' in dir() else None,
                content=content,
                publish_date=None,
                word_count=word_count,
                content_hash=content_hash,
                fetch_time=datetime.utcnow(),
            )

        except TranscriptsDisabled:
            logger.info(f"Transcripts disabled for YouTube video {video_id}")
            return None
        except VideoUnavailable:
            logger.info(f"YouTube video {video_id} unavailable")
            return None
        except NoTranscriptFound:
            logger.info(f"No transcript found for YouTube video {video_id}")
            return None
        except Exception as e:
            logger.warning(f"Failed to fetch YouTube transcript for {video_id}: {e}")
            return None

    async def fetch(
        self,
        url: str,
        extract_main_content: bool = True,
    ) -> FetchedContent:
        """Fetch and extract content from a URL.

        Args:
            url: URL to fetch
            extract_main_content: Whether to extract just main content (default True)

        Returns:
            FetchedContent with extracted text and metadata
        """
        if self._is_youtube_url(url):
            youtube_content = await self._fetch_youtube_transcript(url)
            if youtube_content:
                return youtube_content
            logger.info(f"YouTube transcript unavailable for {url}, skipping (video content not extractable)")
            return FetchedContent(
                url=url,
                title="YouTube Video (transcript unavailable)",
                author=None,
                content="[Video content - transcript not available]",
                publish_date=None,
                word_count=0,
                content_hash=hashlib.sha256(url.encode()).hexdigest()[:16],
                fetch_time=datetime.utcnow(),
            )

        try:
            response = await self._client.get(url)
            response.raise_for_status()
            html = response.text

            if extract_main_content:
                extracted = bare_extraction(
                    html,
                    url=url,
                    include_comments=False,
                    include_tables=True,
                    include_links=False,
                    with_metadata=True,
                    config=trafilatura_config,
                )

                if extracted and isinstance(extracted, dict):
                    content = extracted.get("text", "") or ""
                    title = extracted.get("title") or self._extract_title_from_html(html)
                    author = extracted.get("author")
                    date_str = extracted.get("date")
                    publish_date = self._parse_date(date_str)

                    if not author:
                        author = self._extract_author_from_html(html, url)
                    if not publish_date:
                        publish_date = self._extract_date_from_html(html)
                else:
                    content = extract(html, url=url, config=trafilatura_config) or ""
                    title = self._extract_title_from_html(html)
                    author = self._extract_author_from_html(html, url)
                    publish_date = self._extract_date_from_html(html)
            else:
                content = html
                title = None
                author = None
                publish_date = None

            content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
            word_count = len(content.split())

            logger.info(f"Fetched {url}: {word_count} words")

            return FetchedContent(
                url=url,
                title=title,
                author=author,
                content=content,
                publish_date=publish_date,
                word_count=word_count,
                content_hash=content_hash,
                fetch_time=datetime.utcnow(),
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching {url}: {e.response.status_code}")
            raise
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            raise

    def _extract_title_from_html(self, html: str) -> str | None:
        """Extract title from HTML."""
        if "<title>" in html:
            start = html.find("<title>") + 7
            end = html.find("</title>")
            if end > start:
                return html[start:end].strip()
        return None

    def _extract_author_from_html(self, html: str, url: str = "") -> str | None:
        """Extract author from HTML meta tags or infer from source."""
        patterns = [
            r'<meta[^>]+name=["\']author["\'][^>]+content=["\'](.*?)["\']',
            r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']author["\']',
            r'<meta[^>]+property=["\']article:author["\'][^>]+content=["\'](.*?)["\']',
            r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']article:author["\']',
            r'"author":\s*\{\s*"name":\s*"([^"]+)"',
            r'"author":\s*"([^"]+)"',
            r'<span[^>]+class="[^"]*author[^"]*"[^>]*>([^<]+)</span>',
            r'<a[^>]+rel=["\']author["\'][^>]*>([^<]+)</a>',
            r'class="byline[^"]*"[^>]*>(?:By\s*)?([^<]+)<',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                author = match.group(1).strip()
                if author and author.lower() not in ["unknown", "anonymous", "", "null"]:
                    return author

        if url:
            url_lower = url.lower()
            if "wikipedia.org" in url_lower:
                return "Wikipedia Contributors"
            elif "imdb.com" in url_lower:
                return "IMDb"
            elif "themoviedb.org" in url_lower or "tmdb" in url_lower:
                return "TMDB"
            elif "britannica.com" in url_lower:
                return "Encyclopaedia Britannica"
            elif "bbc.com" in url_lower or "bbc.co.uk" in url_lower:
                return "BBC"
            elif "nytimes.com" in url_lower:
                return "The New York Times"
            elif "theguardian.com" in url_lower:
                return "The Guardian"
            elif "reuters.com" in url_lower:
                return "Reuters"
            elif "apnews.com" in url_lower:
                return "Associated Press"

        return None

    def _extract_date_from_html(self, html: str) -> datetime | None:
        """Extract publish date from HTML meta tags."""
        patterns = [
            r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\'](.*?)["\']',
            r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']article:published_time["\']',
            r'<meta[^>]+property=["\']article:modified_time["\'][^>]+content=["\'](.*?)["\']',
            r'<meta[^>]+name=["\']date["\'][^>]+content=["\'](.*?)["\']',
            r'<meta[^>]+name=["\']publish[_-]?date["\'][^>]+content=["\'](.*?)["\']',
            r'<meta[^>]+name=["\']DC\.date["\'][^>]+content=["\'](.*?)["\']',
            r'<meta[^>]+name=["\']last-modified["\'][^>]+content=["\'](.*?)["\']',
            r'"datePublished":\s*"([^"]+)"',
            r'"publishedDate":\s*"([^"]+)"',
            r'"dateModified":\s*"([^"]+)"',
            r'"dateCreated":\s*"([^"]+)"',
            r'<time[^>]+datetime=["\']([^"\']+)["\']',
            r'class="[^"]*date[^"]*"[^>]*>(\d{1,2}\s+\w+\s+\d{4})',
            r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                parsed = self._parse_date(match.group(1))
                if parsed:
                    return parsed
        return None

    def _parse_date(self, date_str: str | None) -> datetime | None:
        """Parse date string into datetime using multiple formats."""
        if not date_str:
            return None
        try:
            return date_parser.parse(date_str)
        except (ValueError, TypeError):
            pass
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError:
            pass
        return None

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()


_web_fetch_service: WebFetchService | None = None


def get_web_fetch_service() -> WebFetchService:
    """Get the singleton web fetch service instance."""
    global _web_fetch_service
    if _web_fetch_service is None:
        _web_fetch_service = WebFetchService()
    return _web_fetch_service
