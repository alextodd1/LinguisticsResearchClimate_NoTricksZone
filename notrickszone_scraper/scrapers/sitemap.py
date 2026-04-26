"""
Article discovery from XML sitemaps.
"""

import logging
from datetime import datetime
from typing import List, Optional
from xml.etree import ElementTree

from ..config import ScraperConfig
from ..models import ArticleStub
from ..utils.http_client import HTTPClient
from ..storage.database import ScraperDatabase

logger = logging.getLogger(__name__)

# XML sitemap namespace
SITEMAP_NS = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}


class SitemapScraper:
    """Scraper for discovering articles from XML sitemaps."""

    def __init__(self, config: ScraperConfig, http_client: HTTPClient, db: ScraperDatabase):
        self.config = config
        self.http = http_client
        self.db = db

    def discover_all_articles(self) -> int:
        """
        Discover all articles in date range from sitemaps.

        Returns:
            Total number of new articles discovered
        """
        total_new = 0

        # Step 1: Fetch sitemap index to get all post-sitemap URLs
        sitemap_urls = self._fetch_sitemap_index()

        if not sitemap_urls:
            logger.warning("No post sitemaps found in sitemap index")
            return 0

        logger.info(f"Found {len(sitemap_urls)} post sitemaps to process")

        # Step 2: Process each sitemap
        for sitemap_url in sitemap_urls:
            # Track in database
            self.db.add_sitemap(sitemap_url)

            # Skip if already processed
            if self.db.is_sitemap_complete(sitemap_url):
                logger.debug(f"Skipping {sitemap_url} - already complete")
                continue

            logger.info(f"Processing sitemap: {sitemap_url}")
            articles = self._fetch_sitemap(sitemap_url)

            # Filter by date range
            filtered = self._filter_by_date(articles)

            # Add to database
            new_count = self.db.add_article_stubs(filtered)
            total_new += new_count

            # Mark sitemap as complete
            self.db.mark_sitemap_complete(sitemap_url, len(filtered))

            logger.info(f"Sitemap {sitemap_url}: {len(filtered)} articles in range, {new_count} new")

        return total_new

    def _fetch_sitemap_index(self) -> List[str]:
        """
        Fetch the sitemap index and extract post-sitemap URLs.

        Returns:
            List of post-sitemap URLs
        """
        index_url = f"{self.config.base_url}/sitemap.xml"
        logger.info(f"Fetching sitemap index: {index_url}")

        try:
            response = self.http.get_with_retry(index_url)
            if not response:
                logger.error("Failed to fetch sitemap index")
                return []

            root = ElementTree.fromstring(response.content)

            # Parse sitemap index - look for <sitemap><loc> entries
            sitemap_urls = []

            # WordPress core sitemaps use the URL pattern wp-sitemap-posts-post-N.xml
            # for blog posts (distinct from -page-N.xml or -taxonomies-* entries).
            # Yoast and other plugins use post-sitemap.xml, so accept both.
            def _is_post_sitemap(u: str) -> bool:
                ul = u.lower()
                return 'wp-sitemap-posts-post' in ul or 'post-sitemap' in ul

            for sitemap in root.findall('.//sm:sitemap', SITEMAP_NS):
                loc = sitemap.find('sm:loc', SITEMAP_NS)
                if loc is not None and loc.text:
                    url = loc.text.strip()
                    if _is_post_sitemap(url):
                        sitemap_urls.append(url)

            # If no namespace match, try without namespace
            if not sitemap_urls:
                for sitemap in root.iter():
                    if sitemap.tag.endswith('loc'):
                        url = sitemap.text.strip() if sitemap.text else ''
                        if _is_post_sitemap(url):
                            sitemap_urls.append(url)

            logger.info(f"Found {len(sitemap_urls)} post sitemaps")
            return sorted(sitemap_urls)

        except ElementTree.ParseError as e:
            logger.error(f"Error parsing sitemap index XML: {e}")
            return []
        except Exception as e:
            logger.error(f"Error fetching sitemap index: {e}")
            return []

    def _fetch_sitemap(self, sitemap_url: str) -> List[ArticleStub]:
        """
        Fetch and parse a single post sitemap.

        Args:
            sitemap_url: URL of the sitemap

        Returns:
            List of ArticleStub objects
        """
        try:
            response = self.http.get_with_retry(sitemap_url)
            if not response:
                logger.warning(f"Failed to fetch sitemap: {sitemap_url}")
                return []

            root = ElementTree.fromstring(response.content)
            articles = []

            # Parse URL entries
            for url_elem in root.findall('.//sm:url', SITEMAP_NS):
                loc = url_elem.find('sm:loc', SITEMAP_NS)
                lastmod = url_elem.find('sm:lastmod', SITEMAP_NS)

                if loc is not None and loc.text:
                    article_url = loc.text.strip()

                    # Skip non-article URLs (pages, homepage, etc.)
                    if not self._is_article_url(article_url):
                        continue

                    date_hint = None
                    if lastmod is not None and lastmod.text:
                        date_hint = lastmod.text.strip()

                    articles.append(ArticleStub(
                        url=article_url,
                        title="",  # Title not available in sitemap
                        date_hint=date_hint,
                    ))

            # If no namespace match, try without namespace
            if not articles:
                for url_elem in root.iter():
                    if url_elem.tag.endswith('}url') or url_elem.tag == 'url':
                        loc = None
                        lastmod_text = None
                        for child in url_elem:
                            tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                            if tag == 'loc' and child.text:
                                loc = child.text.strip()
                            elif tag == 'lastmod' and child.text:
                                lastmod_text = child.text.strip()

                        if loc and self._is_article_url(loc):
                            articles.append(ArticleStub(
                                url=loc,
                                title="",
                                date_hint=lastmod_text,
                            ))

            logger.debug(f"Found {len(articles)} article URLs in {sitemap_url}")
            return articles

        except ElementTree.ParseError as e:
            logger.error(f"Error parsing sitemap XML {sitemap_url}: {e}")
            return []
        except Exception as e:
            logger.error(f"Error fetching sitemap {sitemap_url}: {e}")
            return []

    def _is_article_url(self, url: str) -> bool:
        """Check if URL looks like an article URL (not a page, tag, category)."""
        if not url:
            return False

        # Must be on the configured domain
        from urllib.parse import urlparse
        host = urlparse(self.config.base_url).netloc.lower()
        if host and host not in url.lower():
            return False

        skip_patterns = [
            '/category/', '/tag/', '/author/', '/page/',
            '/wp-content/', '/wp-admin/', '/wp-includes/',
            '/feed/', '/comments/feed/', '/comment-page-',
            '/about/', '/contact/', '/privacy-policy/',
            '/support/',
        ]

        url_lower = url.lower()
        for pattern in skip_patterns:
            if pattern in url_lower:
                return False

        parsed = urlparse(url)
        path = parsed.path.strip('/')

        if not path:
            return False

        # NoTricksZone permalinks are /YYYY/MM/DD/slug/ — require that shape
        # so non-post URLs that slipped past the skip list are filtered out.
        import re
        if not re.match(r'^\d{4}/\d{2}/\d{2}/[^/]+', path):
            return False

        return True

    def _filter_by_date(self, articles: List[ArticleStub]) -> List[ArticleStub]:
        """
        Filter articles by date range.

        NoTricksZone permalinks embed the publish date as /YYYY/MM/DD/slug, so
        we filter on the URL-derived date as the primary signal. Sitemap
        lastmod is unreliable here because comment activity bumps it forward,
        which would let pre-2017 articles slip through and waste HTTP requests.
        """
        if not self.config.start_date and not self.config.end_date:
            return articles

        import re
        url_date_re = re.compile(r'/(\d{4})/(\d{2})/(\d{2})/')

        filtered = []

        for article in articles:
            dt = None

            m = url_date_re.search(article.url)
            if m:
                try:
                    dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                except ValueError:
                    dt = None

            if dt is None and article.date_hint:
                try:
                    date_str = article.date_hint
                    if 'T' in date_str:
                        dt = datetime.fromisoformat(date_str.split('+')[0].split('Z')[0])
                    else:
                        dt = datetime.fromisoformat(date_str)
                except (ValueError, TypeError):
                    dt = None

            if dt is None:
                filtered.append(article)
                continue

            if self.config.start_date and dt < self.config.start_date:
                continue
            if self.config.end_date and dt > self.config.end_date:
                continue

            filtered.append(article)

        logger.debug(f"Filtered {len(articles)} -> {len(filtered)} articles by date range")
        return filtered

    def get_progress(self) -> dict:
        """Get discovery progress."""
        pending = self.db.get_pending_sitemaps()

        return {
            'pending_sitemaps': len(pending),
        }
