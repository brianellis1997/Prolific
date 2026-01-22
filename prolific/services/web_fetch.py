"""Web content fetching and extraction service.

Fetches URLs and extracts main content using trafilatura
for clean text extraction.
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime

import httpx
from trafilatura import extract, fetch_url
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
                result = extract(
                    html,
                    url=url,
                    include_comments=False,
                    include_tables=True,
                    include_links=False,
                    output_format="txt",
                    config=trafilatura_config,
                )
                content = result or ""

                metadata = extract(
                    html,
                    url=url,
                    output_format="xml",
                    config=trafilatura_config,
                )
                title = self._extract_title(html, metadata)
                author = self._extract_author(metadata)
                publish_date = self._extract_date(metadata)
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

    def _extract_title(self, html: str, metadata: str | None) -> str | None:
        """Extract title from HTML or metadata."""
        if metadata and "<title>" in metadata:
            start = metadata.find("<title>") + 7
            end = metadata.find("</title>")
            if end > start:
                return metadata[start:end].strip()

        if "<title>" in html:
            start = html.find("<title>") + 7
            end = html.find("</title>")
            if end > start:
                return html[start:end].strip()
        return None

    def _extract_author(self, metadata: str | None) -> str | None:
        """Extract author from metadata."""
        if metadata and 'author="' in metadata:
            start = metadata.find('author="') + 8
            end = metadata.find('"', start)
            if end > start:
                return metadata[start:end].strip()
        return None

    def _extract_date(self, metadata: str | None) -> datetime | None:
        """Extract publish date from metadata."""
        if metadata and 'date="' in metadata:
            start = metadata.find('date="') + 6
            end = metadata.find('"', start)
            if end > start:
                date_str = metadata[start:end].strip()
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
