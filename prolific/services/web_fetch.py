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

try:
    import fitz  # PyMuPDF
    PDF_EXTRACTION_AVAILABLE = True
except ImportError:
    PDF_EXTRACTION_AVAILABLE = False

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
    PDF_EXTENSIONS = {".pdf"}

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
            api = YouTubeTranscriptApi()

            transcript_data = None
            try:
                fetched = api.fetch(video_id, languages=['en'])
                transcript_data = fetched.to_raw_data()
            except NoTranscriptFound:
                transcript_list = api.list(video_id)
                for t in transcript_list:
                    try:
                        translated = t.translate('en')
                        transcript_data = translated.fetch().to_raw_data()
                        break
                    except Exception:
                        continue

            if not transcript_data:
                logger.info(f"No transcript available for YouTube video {video_id}")
                return None

            full_text = " ".join(entry["text"] for entry in transcript_data)
            full_text = re.sub(r'\s+', ' ', full_text).strip()

            video_title = f"YouTube Video {video_id}"
            author = None
            try:
                response = await self._client.get(
                    f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
                )
                if response.status_code == 200:
                    oembed = response.json()
                    video_title = oembed.get("title", video_title)
                    author = oembed.get("author_name")
            except Exception:
                pass

            content = f"[YouTube Video Transcript]\n\nTitle: {video_title}\n\n{full_text}"
            content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
            word_count = len(content.split())

            logger.info(f"Fetched YouTube transcript for {video_id}: {word_count} words")

            return FetchedContent(
                url=url,
                title=video_title,
                author=author,
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

    def _is_pdf_url(self, url: str) -> bool:
        """Check if URL points to a PDF file."""
        try:
            parsed = urlparse(url)
            path_lower = parsed.path.lower()
            return any(path_lower.endswith(ext) for ext in self.PDF_EXTENSIONS)
        except Exception:
            return False

    async def _fetch_pdf_content(self, url: str) -> FetchedContent | None:
        """Fetch and extract text from a PDF URL.

        Args:
            url: URL to a PDF file

        Returns:
            FetchedContent with extracted text, or None if extraction fails
        """
        if not PDF_EXTRACTION_AVAILABLE:
            logger.warning("PyMuPDF not installed, cannot extract PDF content")
            return None

        try:
            response = await self._client.get(url)
            response.raise_for_status()
            pdf_bytes = response.content

            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            num_pages = len(doc)
            text_parts = []
            for page_num in range(num_pages):
                page = doc[page_num]
                text_parts.append(page.get_text())
            doc.close()

            content = "\n\n".join(text_parts)
            content = re.sub(r'\n{3,}', '\n\n', content)
            content = content.strip()

            if not content:
                logger.warning(f"PDF extracted but no text content: {url}")
                return None

            title = url.split("/")[-1].replace(".pdf", "").replace("-", " ").replace("_", " ").title()
            content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
            word_count = len(content.split())

            logger.info(f"Extracted PDF {url}: {word_count} words from {num_pages} pages")

            return FetchedContent(
                url=url,
                title=title,
                author=None,
                content=f"[PDF Document]\n\n{content}",
                publish_date=None,
                word_count=word_count,
                content_hash=content_hash,
                fetch_time=datetime.utcnow(),
            )

        except Exception as e:
            logger.warning(f"Failed to extract PDF from {url}: {e}")
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

        if self._is_pdf_url(url):
            pdf_content = await self._fetch_pdf_content(url)
            if pdf_content:
                return pdf_content
            logger.info(f"PDF extraction failed for {url}")
            return FetchedContent(
                url=url,
                title="PDF Document (extraction failed)",
                author=None,
                content="[PDF content - extraction failed]",
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
        # Limit HTML size to prevent regex catastrophic backtracking
        # Meta tags are in <head> which is always in the first 50KB
        html_limited = html[:50000]

        # Simpler, faster patterns that avoid backtracking
        # Use {0,200} instead of + to limit backtracking
        patterns = [
            r'<meta[^>]{0,200}name=["\']author["\'][^>]{0,200}content=["\']([^"\']{1,200})["\']',
            r'<meta[^>]{0,200}content=["\']([^"\']{1,200})["\'][^>]{0,200}name=["\']author["\']',
            r'<meta[^>]{0,200}property=["\']article:author["\'][^>]{0,200}content=["\']([^"\']{1,200})["\']',
            r'"author":\s*\{\s*"name":\s*"([^"]{1,200})"',
            r'"author":\s*"([^"]{1,200})"',
        ]
        for pattern in patterns:
            try:
                match = re.search(pattern, html_limited, re.IGNORECASE)
                if match:
                    author = match.group(1).strip()
                    if author and author.lower() not in ["unknown", "anonymous", "", "null"]:
                        return author
            except re.error:
                continue

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
        # Limit HTML size to prevent regex catastrophic backtracking
        html_limited = html[:50000]

        # Simpler patterns with bounded quantifiers to prevent backtracking
        patterns = [
            r'<meta[^>]{0,200}property=["\']article:published_time["\'][^>]{0,200}content=["\']([^"\']{1,50})["\']',
            r'<meta[^>]{0,200}property=["\']article:modified_time["\'][^>]{0,200}content=["\']([^"\']{1,50})["\']',
            r'<meta[^>]{0,200}name=["\']date["\'][^>]{0,200}content=["\']([^"\']{1,50})["\']',
            r'"datePublished":\s*"([^"]{1,50})"',
            r'"dateModified":\s*"([^"]{1,50})"',
            r'<time[^>]{0,100}datetime=["\']([^"\']{1,50})["\']',
            r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})',
        ]
        for pattern in patterns:
            try:
                match = re.search(pattern, html_limited, re.IGNORECASE)
                if match:
                    parsed = self._parse_date(match.group(1))
                    if parsed:
                        return parsed
            except re.error:
                continue
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
