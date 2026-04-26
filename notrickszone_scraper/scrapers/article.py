"""
Article content scraper.
"""

import logging
from datetime import datetime
from typing import Optional

from ..config import ScraperConfig
from ..models import Article
from ..utils.http_client import HTTPClient
from ..parsers.html_parser import ArticleParser
from ..storage.database import ScraperDatabase

logger = logging.getLogger(__name__)


class ArticleScraper:
    """Scraper for individual article pages."""

    def __init__(self, config: ScraperConfig, http_client: HTTPClient, db: ScraperDatabase):
        self.config = config
        self.http = http_client
        self.db = db
        self.parser = ArticleParser(config.base_url)

    def scrape_article(self, url: str) -> Optional[Article]:
        """
        Scrape a single article.

        Args:
            url: Article URL

        Returns:
            Article object or None if failed
        """
        # Check if already scraped
        if self.db.is_article_scraped(url):
            logger.debug(f"Article already scraped: {url}")
            return None

        logger.info(f"Scraping article: {url}")

        try:
            response = self.http.get_with_retry(url)

            if response is None:
                self.db.mark_article_unavailable(url)
                return None

            article = self.parser.parse_article(response.text, url)

            # Verify article is within date range
            if article.date_published:
                if self.config.start_date and article.date_published < self.config.start_date:
                    logger.info(f"Article {url} published {article.date_published} is before start date, skipping")
                    self.db.mark_article_unavailable(url)
                    return None
                if self.config.end_date and article.date_published > self.config.end_date:
                    logger.info(f"Article {url} published {article.date_published} is after end date, skipping")
                    self.db.mark_article_unavailable(url)
                    return None

            # Store the raw HTML for comment parsing later
            article.content_html = response.text

            # Update database
            self.db.update_article(article)

            logger.info(f"Scraped: {article.title[:50]}... ({article.comment_count} comments)")

            return article

        except Exception as e:
            logger.error(f"Error scraping article {url}: {e}")
            self.db.mark_article_failed(url, str(e))
            return None

    def scrape_pending_articles(self, limit: int = 100) -> int:
        """
        Scrape pending articles from database.

        Args:
            limit: Maximum articles to scrape in this batch

        Returns:
            Number of articles successfully scraped
        """
        pending = self.db.get_pending_articles(limit)
        scraped = 0

        for url in pending:
            article = self.scrape_article(url)
            if article:
                scraped += 1

        logger.info(f"Scraped {scraped}/{len(pending)} articles")
        return scraped

    def retry_failed_articles(self, max_retries: int = 3) -> int:
        """
        Retry failed articles.

        Args:
            max_retries: Maximum retries per article

        Returns:
            Number of articles successfully scraped on retry
        """
        failed = self.db.get_failed_articles(max_retries)
        scraped = 0

        for url in failed:
            article = self.scrape_article(url)
            if article:
                scraped += 1

        logger.info(f"Rescued {scraped}/{len(failed)} failed articles")
        return scraped

    def get_article_html(self, url: str) -> Optional[str]:
        """
        Get raw HTML for an article (for comment extraction).

        Args:
            url: Article URL

        Returns:
            HTML content or None
        """
        try:
            response = self.http.get_with_retry(url)
            if response:
                return response.text
        except Exception as e:
            logger.error(f"Error fetching article HTML {url}: {e}")

        return None
