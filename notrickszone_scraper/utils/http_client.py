"""
HTTP client with rate limiting, retries, and proper headers.
"""

import logging
import time
import random
from typing import Optional, Dict, Any
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..config import ScraperConfig
from .rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class HTTPClient:
    """HTTP client with polite scraping features."""

    # Rotating user agents for variety
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    ]

    def __init__(self, config: ScraperConfig):
        self.config = config
        self.rate_limiter = RateLimiter(delay=config.request_delay)
        self.session = self._create_session()
        self._request_count = 0

    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic."""
        session = requests.Session()

        # Configure retries
        retry_strategy = Retry(
            total=self.config.max_retries,
            backoff_factor=1,  # 1, 2, 4, 8... seconds
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST", "OPTIONS"]
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        # Set default headers
        session.headers.update(self._get_headers())

        return session

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with rotating user agent."""
        return {
            "User-Agent": random.choice(self.USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }

    def get(self, url: str, **kwargs) -> requests.Response:
        """
        Make a GET request with rate limiting.

        Args:
            url: URL to fetch
            **kwargs: Additional arguments for requests.get

        Returns:
            Response object

        Raises:
            requests.RequestException: On request failure
        """
        self.rate_limiter.wait()
        self._request_count += 1

        # Rotate user agent periodically
        if self._request_count % 10 == 0:
            self.session.headers.update({"User-Agent": random.choice(self.USER_AGENTS)})

        # Set timeout
        kwargs.setdefault('timeout', self.config.timeout)

        logger.debug(f"GET {url}")

        try:
            response = self.session.get(url, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                # Rate limited - increase delay
                logger.warning(f"Rate limited on {url}, increasing delay")
                self._handle_rate_limit()
                raise
            elif e.response.status_code == 404:
                logger.warning(f"Not found: {url}")
                raise
            else:
                logger.error(f"HTTP error {e.response.status_code} for {url}")
                raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed for {url}: {e}")
            raise

    def get_with_retry(self, url: str, max_attempts: int = None) -> Optional[requests.Response]:
        """
        Get with exponential backoff retry.

        Args:
            url: URL to fetch
            max_attempts: Maximum retry attempts (default from config)

        Returns:
            Response or None if all retries failed
        """
        max_attempts = max_attempts or self.config.max_retries

        for attempt in range(max_attempts):
            try:
                return self.get(url)
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    return None  # Don't retry 404s
                if attempt < max_attempts - 1:
                    delay = self.config.request_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.info(f"Retry {attempt + 1}/{max_attempts} for {url} after {delay:.1f}s")
                    time.sleep(delay)
                else:
                    logger.error(f"All retries exhausted for {url}")
                    raise
            except requests.exceptions.RequestException:
                if attempt < max_attempts - 1:
                    delay = self.config.request_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.info(f"Retry {attempt + 1}/{max_attempts} for {url} after {delay:.1f}s")
                    time.sleep(delay)
                else:
                    raise

        return None

    def _handle_rate_limit(self):
        """Handle rate limiting by increasing delay."""
        current_delay = self.rate_limiter.delay
        new_delay = min(current_delay * 2, 30)  # Max 30 seconds
        self.rate_limiter.set_delay(new_delay)
        logger.warning(f"Increased request delay to {new_delay}s")

    def download_image(self, url: str, save_path: str) -> bool:
        """
        Download an image to a file.

        Args:
            url: Image URL
            save_path: Local path to save

        Returns:
            True if successful
        """
        try:
            self.rate_limiter.wait()
            response = self.session.get(url, stream=True, timeout=self.config.timeout)
            response.raise_for_status()

            # Check content length
            content_length = response.headers.get('content-length')
            if content_length:
                size_mb = int(content_length) / (1024 * 1024)
                if size_mb > self.config.max_image_size_mb:
                    logger.warning(f"Image too large ({size_mb:.1f}MB): {url}")
                    return False

            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.debug(f"Downloaded image: {url} -> {save_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to download image {url}: {e}")
            return False

    def make_url(self, path: str) -> str:
        """Make absolute URL from relative path."""
        return urljoin(self.config.base_url, path)

    @property
    def request_count(self) -> int:
        """Total requests made."""
        return self._request_count
