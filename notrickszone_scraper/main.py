#!/usr/bin/env python3
"""
NoTricksZone Scraper - Main entry point.

Web scraper for notrickszone.com for linguistic research.
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import ScraperConfig
from .storage.database import ScraperDatabase
from .storage.file_manager import FileManager
from .utils.http_client import HTTPClient
from .scrapers.sitemap import SitemapScraper
from .scrapers.article import ArticleScraper
from .scrapers.comments import CommentScraper
from .processors.vertical_writer import VerticalWriter


def setup_logging(log_dir: Path, verbose: bool = False):
    """Configure detailed logging with file and console output."""
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / f"scraper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    level = logging.DEBUG if verbose else logging.INFO

    file_format = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    console_format = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%H:%M:%S'
    )

    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_format)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(console_format)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('chardet').setLevel(logging.WARNING)
    logging.getLogger('charset_normalizer').setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)
    logger.info(f"Logging initialized - Log file: {log_file}")
    logger.info(f"Log level: {'DEBUG' if verbose else 'INFO'}")

    return logger


class NoTricksZoneScraper:
    """Main scraper orchestrator."""

    def __init__(self, config: ScraperConfig):
        self.config = config
        config.create_directories()

        self.db = ScraperDatabase(config.db_path)
        self.http = HTTPClient(config)
        self.file_manager = FileManager(config)

        self.sitemap_scraper = SitemapScraper(config, self.http, self.db)
        self.article_scraper = ArticleScraper(config, self.http, self.db)
        self.comment_scraper = CommentScraper(config, self.http, self.db)
        self.vertical_writer = VerticalWriter(config)

        self.logger = logging.getLogger(__name__)
        self.session_id = None

    def run(self, discover_only: bool = False, scrape_only: bool = False,
            comments_only: bool = False, limit: int = 0):
        """
        Run the full scraping pipeline.

        Args:
            discover_only: Only discover articles, don't scrape
            scrape_only: Only scrape articles, skip discovery
            comments_only: Only scrape comments for already-scraped articles
            limit: Maximum articles to process (0 = all)
        """
        self.session_id = self.db.start_session()
        self.logger.info(f"Starting scrape session {self.session_id}")
        self.logger.info(f"Date range: {self.config.start_date} to {self.config.end_date}")

        articles_scraped = 0
        comments_scraped = 0

        try:
            # Phase 1: Discover articles from sitemaps
            if not scrape_only and not comments_only:
                self.logger.info("Phase 1: Discovering articles from sitemaps...")
                new_articles = self.sitemap_scraper.discover_all_articles()
                self.logger.info(f"Discovered {new_articles} new articles")

                if discover_only:
                    self._print_stats()
                    return

            # Phase 2: Scrape articles and comments
            if not comments_only:
                self.logger.info("Phase 2: Scraping articles and comments...")
                articles_scraped, comments_scraped = self._scrape_articles(limit)

            # Phase 3: Comments only mode
            if comments_only:
                self.logger.info("Scraping comments for existing articles...")
                comments_scraped = self._scrape_comments_only(limit)

        except KeyboardInterrupt:
            self.logger.info("Scraping interrupted by user")
        except Exception as e:
            self.logger.error(f"Scraping failed: {e}", exc_info=True)
        finally:
            self.db.end_session(self.session_id, articles_scraped, comments_scraped)
            self._print_stats()

    def _scrape_articles(self, limit: int = 0) -> tuple:
        """Scrape pending articles with their comments."""
        articles_scraped = 0
        comments_scraped = 0

        while True:
            batch_size = min(100, limit - articles_scraped) if limit else 100
            pending = self.db.get_pending_articles(batch_size)

            if not pending:
                self.logger.info("No more pending articles")
                break

            for url in pending:
                try:
                    article = self.article_scraper.scrape_article(url)

                    if article:
                        # Scrape comments
                        comments = self.comment_scraper.scrape_comments(
                            article,
                            html_content=article.content_html
                        )
                        article.comments = comments

                        # Download images if enabled
                        if self.config.download_images and comments:
                            self.comment_scraper.download_comment_images(comments, article.id)

                        # Write to all output formats
                        self.vertical_writer.write_article(article)

                        articles_scraped += 1
                        comments_scraped += len(comments)

                        self.logger.info(
                            f"Scraped [{articles_scraped}]: {article.title[:40]}... "
                            f"({len(comments)} comments)"
                        )

                except Exception as e:
                    self.logger.error(f"Error processing {url}: {e}")
                    self.db.mark_article_failed(url, str(e))

                if limit and articles_scraped >= limit:
                    break

            if limit and articles_scraped >= limit:
                break

        return articles_scraped, comments_scraped

    def _scrape_comments_only(self, limit: int = 0) -> int:
        """Scrape comments for already-scraped articles."""
        self.logger.warning("Comments-only mode not fully implemented yet")
        return 0

    def _print_stats(self):
        """Print current statistics."""
        report = self.vertical_writer.generate_stats_report(self.db)
        print(report)

    def test_scrape(self, url: str):
        """
        Test scraping a single article.

        Args:
            url: Article URL to test
        """
        self.logger.info(f"Test scraping: {url}")

        # Fetch and parse
        response = self.http.get_with_retry(url)
        if not response:
            self.logger.error("Failed to fetch article")
            return

        # Parse article
        from .parsers.html_parser import ArticleParser

        article_parser = ArticleParser(self.config.base_url)
        article = article_parser.parse_article(response.text, url)

        print("\n=== ARTICLE ===")
        print(f"ID: {article.id}")
        print(f"Title: {article.title}")
        print(f"Author: {article.author}")
        print(f"Date: {article.date_published}")
        print(f"Categories: {article.categories}")
        print(f"Tags: {article.tags}")
        print(f"Content preview: {article.content_text[:500]}...")
        print(f"Comment count (from page): {article.comment_count}")

        # Use full CommentScraper with pagination support
        comments = self.comment_scraper.scrape_comments(article, html_content=response.text)

        print(f"\n=== COMMENTS ({len(comments)}) ===")
        for i, comment in enumerate(comments[:10]):
            print(f"\n--- Comment {i+1} ---")
            print(f"ID: {comment.id}")
            print(f"Author: {comment.author_name}")
            print(f"Date: {comment.timestamp}")
            print(f"Parent: {comment.parent_id or 'ROOT'}")
            print(f"Depth: {comment.depth}")
            print(f"Images: {len(comment.images)}")
            print(f"Text: {comment.text_clean[:200]}...")

        if len(comments) > 10:
            print(f"\n... and {len(comments) - 10} more comments")

        # Write test output
        article.comments = comments
        test_output_dir = self.config.base_dir / "test_output"
        test_output_dir.mkdir(parents=True, exist_ok=True)

        paths = self.vertical_writer.write_article(article, test_output_dir)
        print(f"\n=== TEST OUTPUT ===")
        print(f"Vertical XML: {paths['vertical_xml']}")
        print(f"Standard XML: {paths['xml']}")
        print(f"Plain text:   {paths['txt']}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="NoTricksZone Scraper - Scrape notrickszone.com for linguistic research"
    )

    parser.add_argument(
        '--config', '-c',
        type=str,
        help='Path to YAML config file'
    )

    parser.add_argument(
        '--output', '-o',
        type=str,
        default='./output',
        help='Output directory (default: ./output)'
    )

    parser.add_argument(
        '--delay', '-d',
        type=float,
        default=2.0,
        help='Delay between requests in seconds (default: 2.0)'
    )

    parser.add_argument(
        '--start-date',
        type=str,
        default='2017-01-20',
        help='Start date (YYYY-MM-DD, default: 2017-01-20)'
    )

    parser.add_argument(
        '--end-date',
        type=str,
        default='2026-01-20',
        help='End date (YYYY-MM-DD, default: 2026-01-20)'
    )

    parser.add_argument(
        '--discover-only',
        action='store_true',
        help='Only discover articles, do not scrape content'
    )

    parser.add_argument(
        '--scrape-only',
        action='store_true',
        help='Only scrape articles, skip discovery phase'
    )

    parser.add_argument(
        '--comments-only',
        action='store_true',
        help='Only scrape comments for already-scraped articles'
    )

    parser.add_argument(
        '--limit', '-l',
        type=int,
        default=0,
        help='Maximum articles to scrape (0 = all)'
    )

    parser.add_argument(
        '--test', '-t',
        type=str,
        help='Test scraping a single article URL'
    )

    parser.add_argument(
        '--stats',
        action='store_true',
        help='Show current scraping statistics'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Verbose logging'
    )

    parser.add_argument(
        '--no-images',
        action='store_true',
        help='Skip downloading comment images'
    )

    parser.add_argument(
        '--db-path',
        type=str,
        help='Path to scraper progress database'
    )

    args = parser.parse_args()

    # Create config
    if args.config:
        config = ScraperConfig.from_yaml(args.config)
    else:
        config = ScraperConfig()

    # Apply command line overrides
    config.base_dir = Path(args.output)
    config.corpus_dir = config.base_dir / "corpus"
    config.vertical_xml_dir = config.base_dir / "vertical_xml"
    config.xml_dir = config.base_dir / "xml"
    config.txt_dir = config.base_dir / "txt"
    config.images_dir = config.base_dir / "images"
    config.metadata_dir = config.base_dir / "metadata"
    config.logs_dir = config.base_dir / "logs"
    config.db_path = config.base_dir / "scraper_progress.db"
    config.request_delay = args.delay

    if args.start_date:
        config.start_date = datetime.fromisoformat(args.start_date)

    if args.end_date:
        config.end_date = datetime.fromisoformat(args.end_date)

    if args.db_path:
        config.db_path = Path(args.db_path)

    if args.no_images:
        config.download_images = False

    # Setup logging
    logger = setup_logging(config.logs_dir, args.verbose)

    # Create scraper
    scraper = NoTricksZoneScraper(config)

    # Handle commands
    if args.stats:
        scraper._print_stats()
        return

    if args.test:
        scraper.test_scrape(args.test)
        return

    # Run main scraping
    scraper.run(
        discover_only=args.discover_only,
        scrape_only=args.scrape_only,
        comments_only=args.comments_only,
        limit=args.limit
    )


if __name__ == '__main__':
    main()
