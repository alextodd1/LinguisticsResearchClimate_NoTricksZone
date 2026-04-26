"""
Comment scraper for native WordPress comments.
"""

import logging
import re
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..config import ScraperConfig
from ..models import Comment, Article, ImageRef
from ..utils.http_client import HTTPClient
from ..parsers.html_parser import CommentParser
from ..storage.database import ScraperDatabase

logger = logging.getLogger(__name__)


class CommentScraper:
    """Scraper for native WordPress comments."""

    def __init__(self, config: ScraperConfig, http_client: HTTPClient, db: ScraperDatabase):
        self.config = config
        self.http = http_client
        self.db = db
        self.parser = CommentParser(config.base_url)

    def scrape_comments(self, article: Article, html_content: Optional[str] = None) -> List[Comment]:
        """
        Scrape all comments from an article, including paginated comments.

        Args:
            article: Article object
            html_content: Optional pre-fetched HTML content

        Returns:
            List of Comment objects
        """
        if not html_content:
            try:
                response = self.http.get_with_retry(article.url)
                if response:
                    html_content = response.text
                else:
                    logger.warning(f"Could not fetch article for comments: {article.url}")
                    return []
            except Exception as e:
                logger.error(f"Error fetching article {article.url}: {e}")
                return []

        # Parse initial comments from page
        comments = self.parser.parse_comments(html_content, article.url)
        logger.debug(f"Found {len(comments)} comments on page 1 of {article.url}")

        # Check for comment pagination (WordPress can paginate comments)
        total_pages = self._get_total_comment_pages(html_content)
        if total_pages > 1:
            logger.info(f"Article {article.id}: Found {total_pages} comment pages, fetching all...")
            paginated_comments = self._scrape_paginated_comments(article.url, total_pages)
            comments.extend(paginated_comments)
            logger.info(f"Article {article.id}: Total comments before dedup: {len(comments)}")

        # Remove duplicates based on comment ID
        seen_ids = set()
        unique_comments = []
        duplicates = 0
        for comment in comments:
            if comment.id not in seen_ids:
                seen_ids.add(comment.id)
                unique_comments.append(comment)
            else:
                duplicates += 1
        comments = unique_comments

        if duplicates > 0:
            logger.debug(f"Removed {duplicates} duplicate comments for article: {article.id}")

        # Save to database
        if comments:
            self.db.add_comments(comments)
            logger.debug(f"Saved {len(comments)} comments to database for article: {article.id}")

        # Log comment statistics
        root_comments = sum(1 for c in comments if c.depth == 0)
        reply_comments = len(comments) - root_comments
        logger.info(f"Article {article.id}: {len(comments)} total comments ({root_comments} root, {reply_comments} replies)")
        return comments

    def _get_total_comment_pages(self, html_content: str) -> int:
        """
        Detect total number of comment pages from pagination.

        Args:
            html_content: HTML content of article page

        Returns:
            Total number of comment pages (1 if no pagination)
        """
        soup = BeautifulSoup(html_content, 'lxml')

        # Look for WordPress comment pagination
        pagination = soup.select(
            '.comment-navigation .page-numbers, '
            '.comments-pagination .page-numbers, '
            '#comments .page-numbers, '
            '.navigation-comments .page-numbers'
        )

        if not pagination:
            return 1

        max_page = 1
        for elem in pagination:
            text = elem.get_text(strip=True)
            if text.isdigit():
                page_num = int(text)
                if page_num > max_page:
                    max_page = page_num

        return max_page

    def _scrape_paginated_comments(self, article_url: str, total_pages: int) -> List[Comment]:
        """
        Scrape comments from all paginated pages (starting from page 2).

        Args:
            article_url: Base article URL
            total_pages: Total number of comment pages

        Returns:
            List of comments from pages 2 onwards
        """
        all_comments = []

        # Remove trailing slash for consistent URL building
        base_url = article_url.rstrip('/')

        for page_num in range(2, total_pages + 1):
            # WordPress comment pagination URL pattern
            page_url = f"{base_url}/comment-page-{page_num}/"

            logger.debug(f"Fetching comment page {page_num}/{total_pages}: {page_url}")

            try:
                response = self.http.get_with_retry(page_url)
                if response and response.status_code == 200:
                    page_comments = self.parser.parse_comments(response.text, article_url)
                    logger.info(f"  Page {page_num}/{total_pages}: {len(page_comments)} comments")
                    all_comments.extend(page_comments)
                else:
                    # Try alternative URL pattern with query parameter
                    alt_url = f"{base_url}?cpage={page_num}"
                    logger.debug(f"Primary URL failed, trying alternative: {alt_url}")
                    response = self.http.get_with_retry(alt_url)
                    if response and response.status_code == 200:
                        page_comments = self.parser.parse_comments(response.text, article_url)
                        logger.info(f"  Page {page_num}/{total_pages}: {len(page_comments)} comments (alt URL)")
                        all_comments.extend(page_comments)
                    else:
                        logger.warning(f"Could not fetch comment page {page_num} - both URL patterns failed")
            except Exception as e:
                logger.error(f"Error fetching comment page {page_num}: {e}", exc_info=True)

        logger.info(f"Pagination complete: {len(all_comments)} comments from pages 2-{total_pages}")
        return all_comments

    def download_comment_images(self, comments: List[Comment], article_id: str) -> int:
        """
        Download images from comments.

        Args:
            comments: List of comments
            article_id: Article identifier

        Returns:
            Number of images downloaded
        """
        if not self.config.download_images:
            return 0

        downloaded = 0

        for comment in comments:
            for idx, image in enumerate(comment.images):
                if image.downloaded:
                    continue

                ext = self._get_image_extension(image.original_url)
                filename = f"{article_id}_{comment.id}_{idx}.{ext}"
                local_path = self.config.images_dir / filename

                success = self.http.download_image(image.original_url, str(local_path))

                if success:
                    image.local_path = str(local_path)
                    image.filename = filename
                    image.downloaded = True
                    downloaded += 1

                    self.db.mark_image_downloaded(
                        image.original_url,
                        str(local_path),
                        filename
                    )

        return downloaded

    def _get_image_extension(self, url: str) -> str:
        """Extract image extension from URL."""
        for ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg']:
            if f'.{ext}' in url.lower():
                return ext
        return 'jpg'
