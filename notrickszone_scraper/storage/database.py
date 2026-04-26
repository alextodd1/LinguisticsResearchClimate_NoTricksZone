"""
SQLite database for tracking scraping progress and resumability.
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
from contextlib import contextmanager

from ..models import Article, Comment, ArticleStub


class ScraperDatabase:
    """SQLite database for tracking scraper progress."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()

    @contextmanager
    def _get_connection(self):
        """Get a database connection with proper cleanup."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_database(self):
        """Initialize database schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Articles discovered table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS articles (
                    url TEXT PRIMARY KEY,
                    article_id TEXT,
                    title TEXT,
                    author TEXT,
                    date_published TEXT,
                    categories TEXT,
                    tags TEXT,
                    comment_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    discovered_at TEXT,
                    scraped_at TEXT,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0
                )
            ''')

            # Comments table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS comments (
                    comment_id TEXT PRIMARY KEY,
                    article_url TEXT,
                    author_name TEXT,
                    author_url TEXT,
                    timestamp TEXT,
                    text_html TEXT,
                    text_clean TEXT,
                    parent_id TEXT,
                    depth INTEGER DEFAULT 0,
                    images TEXT,
                    scraped_at TEXT,
                    FOREIGN KEY (article_url) REFERENCES articles(url)
                )
            ''')

            # Images table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS images (
                    original_url TEXT PRIMARY KEY,
                    local_path TEXT,
                    filename TEXT,
                    article_url TEXT,
                    comment_id TEXT,
                    downloaded INTEGER DEFAULT 0,
                    download_error TEXT,
                    FOREIGN KEY (article_url) REFERENCES articles(url)
                )
            ''')

            # Scrape sessions table for tracking runs
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS scrape_sessions (
                    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT,
                    ended_at TEXT,
                    articles_scraped INTEGER DEFAULT 0,
                    comments_scraped INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'running'
                )
            ''')

            # Sitemaps tracking (replaces archive_months)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sitemaps (
                    sitemap_url TEXT PRIMARY KEY,
                    status TEXT DEFAULT 'pending',
                    article_count INTEGER DEFAULT 0,
                    scraped_at TEXT
                )
            ''')

            # Create indexes for performance
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_articles_date ON articles(date_published)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_comments_article ON comments(article_url)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sitemaps_status ON sitemaps(status)')

    # ========== Article Methods ==========

    def add_article_stub(self, stub: ArticleStub) -> bool:
        """Add an article stub if it doesn't exist. Returns True if added."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute('''
                    INSERT OR IGNORE INTO articles (url, title, discovered_at, status)
                    VALUES (?, ?, ?, 'pending')
                ''', (stub.url, stub.title, datetime.now().isoformat()))
                return cursor.rowcount > 0
            except sqlite3.IntegrityError:
                return False

    def add_article_stubs(self, stubs: List[ArticleStub]) -> int:
        """Add multiple article stubs. Returns count of new articles added."""
        added = 0
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for stub in stubs:
                try:
                    cursor.execute('''
                        INSERT OR IGNORE INTO articles (url, title, discovered_at, status)
                        VALUES (?, ?, ?, 'pending')
                    ''', (stub.url, stub.title, datetime.now().isoformat()))
                    if cursor.rowcount > 0:
                        added += 1
                except sqlite3.IntegrityError:
                    pass
        return added

    def update_article(self, article: Article):
        """Update article with full scraped data."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE articles SET
                    article_id = ?,
                    title = ?,
                    author = ?,
                    date_published = ?,
                    categories = ?,
                    tags = ?,
                    comment_count = ?,
                    status = 'scraped',
                    scraped_at = ?,
                    error_message = NULL
                WHERE url = ?
            ''', (
                article.id,
                article.title,
                article.author,
                article.date_published.isoformat() if article.date_published else None,
                json.dumps(article.categories),
                json.dumps(article.tags),
                article.comment_count,
                datetime.now().isoformat(),
                article.url
            ))

    def mark_article_failed(self, url: str, error: str):
        """Mark an article as failed with error message."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE articles SET
                    status = 'failed',
                    error_message = ?,
                    retry_count = retry_count + 1
                WHERE url = ?
            ''', (error, url))

    def mark_article_unavailable(self, url: str):
        """Mark an article as unavailable (404)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE articles SET status = 'unavailable'
                WHERE url = ?
            ''', (url,))

    def get_pending_articles(self, limit: int = 100) -> List[str]:
        """Get URLs of articles pending scraping."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT url FROM articles
                WHERE status = 'pending'
                ORDER BY discovered_at ASC
                LIMIT ?
            ''', (limit,))
            return [row['url'] for row in cursor.fetchall()]

    def get_failed_articles(self, max_retries: int = 3) -> List[str]:
        """Get URLs of failed articles that can be retried."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT url FROM articles
                WHERE status = 'failed' AND retry_count < ?
                ORDER BY retry_count ASC
            ''', (max_retries,))
            return [row['url'] for row in cursor.fetchall()]

    def get_article_count_by_status(self) -> dict:
        """Get count of articles by status."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT status, COUNT(*) as count
                FROM articles
                GROUP BY status
            ''')
            return {row['status']: row['count'] for row in cursor.fetchall()}

    def is_article_scraped(self, url: str) -> bool:
        """Check if article has been scraped."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT status FROM articles WHERE url = ?
            ''', (url,))
            row = cursor.fetchone()
            return row is not None and row['status'] == 'scraped'

    # ========== Comment Methods ==========

    def add_comments(self, comments: List[Comment]):
        """Add multiple comments to the database."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for comment in comments:
                cursor.execute('''
                    INSERT OR REPLACE INTO comments (
                        comment_id, article_url, author_name, author_url,
                        timestamp, text_html, text_clean,
                        parent_id, depth, images, scraped_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    comment.id,
                    comment.article_id,
                    comment.author_name,
                    comment.author_url,
                    comment.timestamp.isoformat() if comment.timestamp else None,
                    comment.text_html,
                    comment.text_clean,
                    comment.parent_id,
                    comment.depth,
                    json.dumps([img.to_dict() for img in comment.images]),
                    datetime.now().isoformat()
                ))

    def get_comments_for_article(self, article_url: str) -> List[dict]:
        """Get all comments for an article."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM comments
                WHERE article_url = ?
                ORDER BY timestamp ASC
            ''', (article_url,))
            return [dict(row) for row in cursor.fetchall()]

    def get_total_comment_count(self) -> int:
        """Get total number of comments scraped."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) as count FROM comments')
            return cursor.fetchone()['count']

    # ========== Sitemap Methods ==========

    def add_sitemap(self, sitemap_url: str):
        """Add a sitemap URL if it doesn't exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO sitemaps (sitemap_url, status)
                VALUES (?, 'pending')
            ''', (sitemap_url,))

    def mark_sitemap_complete(self, sitemap_url: str, article_count: int):
        """Mark a sitemap as complete."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE sitemaps SET
                    status = 'complete',
                    article_count = ?,
                    scraped_at = ?
                WHERE sitemap_url = ?
            ''', (article_count, datetime.now().isoformat(), sitemap_url))

    def get_pending_sitemaps(self) -> List[str]:
        """Get sitemap URLs that need scraping."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT sitemap_url FROM sitemaps
                WHERE status = 'pending'
                ORDER BY sitemap_url ASC
            ''')
            return [row['sitemap_url'] for row in cursor.fetchall()]

    def is_sitemap_complete(self, sitemap_url: str) -> bool:
        """Check if sitemap has been processed."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT status FROM sitemaps WHERE sitemap_url = ?
            ''', (sitemap_url,))
            row = cursor.fetchone()
            return row is not None and row['status'] == 'complete'

    # ========== Session Methods ==========

    def start_session(self) -> int:
        """Start a new scraping session. Returns session ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO scrape_sessions (started_at, status)
                VALUES (?, 'running')
            ''', (datetime.now().isoformat(),))
            return cursor.lastrowid

    def end_session(self, session_id: int, articles_scraped: int, comments_scraped: int):
        """End a scraping session."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE scrape_sessions SET
                    ended_at = ?,
                    articles_scraped = ?,
                    comments_scraped = ?,
                    status = 'completed'
                WHERE session_id = ?
            ''', (datetime.now().isoformat(), articles_scraped, comments_scraped, session_id))

    # ========== Image Methods ==========

    def add_image(self, original_url: str, article_url: str, comment_id: str = None):
        """Add an image reference."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO images (original_url, article_url, comment_id)
                VALUES (?, ?, ?)
            ''', (original_url, article_url, comment_id))

    def mark_image_downloaded(self, original_url: str, local_path: str, filename: str):
        """Mark an image as downloaded."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE images SET
                    local_path = ?,
                    filename = ?,
                    downloaded = 1
                WHERE original_url = ?
            ''', (local_path, filename, original_url))

    def get_pending_images(self, limit: int = 100) -> List[dict]:
        """Get images pending download."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM images
                WHERE downloaded = 0
                LIMIT ?
            ''', (limit,))
            return [dict(row) for row in cursor.fetchall()]

    # ========== Statistics ==========

    def get_stats(self) -> dict:
        """Get overall scraping statistics."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Article counts
            cursor.execute('SELECT COUNT(*) as total FROM articles')
            total_articles = cursor.fetchone()['total']

            article_counts = self.get_article_count_by_status()

            # Comment count
            cursor.execute('SELECT COUNT(*) as total FROM comments')
            total_comments = cursor.fetchone()['total']

            # Image counts
            cursor.execute('SELECT COUNT(*) as total FROM images')
            total_images = cursor.fetchone()['total']

            cursor.execute('SELECT COUNT(*) as downloaded FROM images WHERE downloaded = 1')
            downloaded_images = cursor.fetchone()['downloaded']

            return {
                'total_articles': total_articles,
                'articles_by_status': article_counts,
                'total_comments': total_comments,
                'total_images': total_images,
                'downloaded_images': downloaded_images
            }
