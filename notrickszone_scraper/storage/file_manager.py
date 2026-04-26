"""
File management for output files.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from ..config import ScraperConfig
from ..models import Article


class FileManager:
    """Manages output files for the scraper."""

    def __init__(self, config: ScraperConfig):
        self.config = config
        config.create_directories()

    def get_corpus_file_path(self, year: int, month: int) -> Path:
        """Get path for a monthly corpus file."""
        filename = f"notrickszone_{year}_{month:02d}.vert"
        return self.config.corpus_dir / filename

    def get_image_path(self, article_id: str, comment_id: str, index: int, extension: str) -> Path:
        """Get path for saving an image."""
        filename = f"{article_id}_{comment_id}_{index}.{extension}"
        return self.config.images_dir / filename

    def save_article_json(self, article: Article):
        """Save article data as JSON for debugging/backup."""
        json_dir = self.config.metadata_dir / "articles"
        json_dir.mkdir(exist_ok=True)

        filename = f"{article.id}.json"
        filepath = json_dir / filename

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(article.to_json())

    def save_articles_index(self, articles: List[Dict]):
        """Save an index of all articles."""
        filepath = self.config.metadata_dir / "articles_index.json"
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(articles, f, indent=2)

    def save_image_mapping(self, mapping: Dict[str, str]):
        """Save mapping of original URLs to local paths."""
        filepath = self.config.metadata_dir / "image_mapping.json"

        # Load existing mapping if present
        existing = {}
        if filepath.exists():
            with open(filepath, 'r', encoding='utf-8') as f:
                existing = json.load(f)

        existing.update(mapping)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(existing, f, indent=2)

    def save_scrape_log(self, log_entry: Dict):
        """Append to scrape log."""
        filepath = self.config.metadata_dir / "scrape_log.json"

        logs = []
        if filepath.exists():
            with open(filepath, 'r', encoding='utf-8') as f:
                logs = json.load(f)

        logs.append(log_entry)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(logs, f, indent=2)

    def append_to_corpus(self, year: int, month: int, content: str):
        """Append content to monthly corpus file."""
        filepath = self.get_corpus_file_path(year, month)
        with open(filepath, 'a', encoding='utf-8') as f:
            f.write(content)
            f.write('\n')
