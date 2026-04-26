"""
Data models for articles and comments.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
import json


@dataclass
class ImageRef:
    """Reference to an image in a comment."""
    original_url: str
    local_path: str = ""
    filename: str = ""
    downloaded: bool = False

    def to_dict(self) -> dict:
        return {
            'original_url': self.original_url,
            'local_path': self.local_path,
            'filename': self.filename,
            'downloaded': self.downloaded
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ImageRef":
        return cls(**data)


@dataclass
class Comment:
    """Represents a single comment on an article."""
    id: str
    article_id: str
    author_name: str
    author_url: Optional[str]
    timestamp: datetime
    text_html: str
    text_clean: str
    parent_id: Optional[str] = None  # None if top-level
    depth: int = 0
    images: List[ImageRef] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'article_id': self.article_id,
            'author_name': self.author_name,
            'author_url': self.author_url,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'text_html': self.text_html,
            'text_clean': self.text_clean,
            'parent_id': self.parent_id,
            'depth': self.depth,
            'images': [img.to_dict() for img in self.images]
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Comment":
        data = data.copy()
        if data.get('timestamp'):
            data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        if data.get('images'):
            data['images'] = [ImageRef.from_dict(img) for img in data['images']]
        return cls(**data)


@dataclass
class Article:
    """Represents a scraped article."""
    id: str
    url: str
    title: str
    author: str
    date_published: datetime
    categories: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    content_html: str = ""
    content_text: str = ""
    comment_count: int = 0
    comments: List[Comment] = field(default_factory=list)
    scraped_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'url': self.url,
            'title': self.title,
            'author': self.author,
            'date_published': self.date_published.isoformat() if self.date_published else None,
            'categories': self.categories,
            'tags': self.tags,
            'content_html': self.content_html,
            'content_text': self.content_text,
            'comment_count': self.comment_count,
            'comments': [c.to_dict() for c in self.comments],
            'scraped_at': self.scraped_at.isoformat() if self.scraped_at else None
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Article":
        data = data.copy()
        if data.get('date_published'):
            data['date_published'] = datetime.fromisoformat(data['date_published'])
        if data.get('scraped_at'):
            data['scraped_at'] = datetime.fromisoformat(data['scraped_at'])
        if data.get('comments'):
            data['comments'] = [Comment.from_dict(c) for c in data['comments']]
        return cls(**data)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class ArticleStub:
    """Minimal article info from listing pages before full scrape."""
    url: str
    title: str = ""
    date_hint: Optional[str] = None  # Date from sitemap lastmod
    comment_count_hint: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            'url': self.url,
            'title': self.title,
            'date_hint': self.date_hint,
            'comment_count_hint': self.comment_count_hint
        }
