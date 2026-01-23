"""Web content fetching and extraction service.

Fetches URLs and extracts main content using trafilatura
for clean text extraction.
"""

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from dateutil import parser as date_parser

import httpx
from trafilatura import extract, bare_extraction
from trafilatura.settings import use_config

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

                if extracted:
                    content = extracted.get("text", "") or ""
                    title = extracted.get("title") or self._extract_title_from_html(html)
                    author = extracted.get("author")
                    date_str = extracted.get("date")
                    publish_date = self._parse_date(date_str)

                    if not author:
                        author = self._extract_author_from_html(html)
                    if not publish_date:
                        publish_date = self._extract_date_from_html(html)
                else:
                    content = ""
                    title = self._extract_title_from_html(html)
                    author = self._extract_author_from_html(html)
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

    def _extract_author_from_html(self, html: str) -> str | None:
        """Extract author from HTML meta tags."""
        patterns = [
            r'<meta[^>]+name=["\']author["\'][^>]+content=["\'](.*?)["\']',
            r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']author["\']',
            r'<meta[^>]+property=["\']article:author["\'][^>]+content=["\'](.*?)["\']',
            r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']article:author["\']',
            r'"author":\s*\{\s*"name":\s*"([^"]+)"',
            r'"author":\s*"([^"]+)"',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                author = match.group(1).strip()
                if author and author.lower() not in ["unknown", "anonymous", ""]:
                    return author
        return None

    def _extract_date_from_html(self, html: str) -> datetime | None:
        """Extract publish date from HTML meta tags."""
        patterns = [
            r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\'](.*?)["\']',
            r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']article:published_time["\']',
            r'<meta[^>]+name=["\']date["\'][^>]+content=["\'](.*?)["\']',
            r'<meta[^>]+name=["\']publish[_-]?date["\'][^>]+content=["\'](.*?)["\']',
            r'"datePublished":\s*"([^"]+)"',
            r'"publishedDate":\s*"([^"]+)"',
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
