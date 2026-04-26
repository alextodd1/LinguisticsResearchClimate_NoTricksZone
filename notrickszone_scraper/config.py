"""
Configuration settings for the NoTricksZone scraper.
"""

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
import yaml


@dataclass
class ScraperConfig:
    """Main configuration for the scraper."""

    # Base settings
    base_url: str = "https://notrickszone.com"
    start_date: datetime = field(default_factory=lambda: datetime(2017, 1, 20))
    end_date: Optional[datetime] = field(default_factory=lambda: datetime(2026, 1, 20))

    # Rate limiting
    request_delay: float = 2.0  # seconds between requests
    max_retries: int = 5
    timeout: int = 30

    # User agent - realistic browser agent
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    # Output directories
    base_dir: Path = field(default_factory=lambda: Path("./output"))
    corpus_dir: Path = field(default_factory=lambda: Path("./output/corpus"))
    vertical_xml_dir: Path = field(default_factory=lambda: Path("./output/vertical_xml"))
    xml_dir: Path = field(default_factory=lambda: Path("./output/xml"))
    txt_dir: Path = field(default_factory=lambda: Path("./output/txt"))
    images_dir: Path = field(default_factory=lambda: Path("./output/images"))
    metadata_dir: Path = field(default_factory=lambda: Path("./output/metadata"))
    logs_dir: Path = field(default_factory=lambda: Path("./logs"))

    # Database
    db_path: Path = field(default_factory=lambda: Path("./output/scraper_progress.db"))

    # Processing options
    download_images: bool = False  # Disabled - not needed for corpus linguistics
    max_image_size_mb: int = 10

    def __post_init__(self):
        """Ensure all paths are Path objects."""
        self.base_dir = Path(self.base_dir)
        self.corpus_dir = Path(self.corpus_dir)
        self.vertical_xml_dir = Path(self.vertical_xml_dir)
        self.xml_dir = Path(self.xml_dir)
        self.txt_dir = Path(self.txt_dir)
        self.images_dir = Path(self.images_dir)
        self.metadata_dir = Path(self.metadata_dir)
        self.logs_dir = Path(self.logs_dir)
        self.db_path = Path(self.db_path)

    def create_directories(self):
        """Create all necessary output directories."""
        for directory in [self.base_dir, self.corpus_dir, self.vertical_xml_dir,
                         self.xml_dir, self.txt_dir, self.images_dir,
                         self.metadata_dir, self.logs_dir]:
            directory.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_yaml(cls, path: str) -> "ScraperConfig":
        """Load configuration from YAML file."""
        with open(path, 'r') as f:
            data = yaml.safe_load(f)

        config = cls()

        if 'scraper' in data:
            scraper = data['scraper']
            if 'base_url' in scraper:
                config.base_url = scraper['base_url']
            if 'start_date' in scraper:
                config.start_date = datetime.fromisoformat(scraper['start_date'])
            if 'end_date' in scraper and scraper['end_date']:
                config.end_date = datetime.fromisoformat(scraper['end_date'])
            if 'request_delay' in scraper:
                config.request_delay = float(scraper['request_delay'])
            if 'max_retries' in scraper:
                config.max_retries = int(scraper['max_retries'])
            if 'timeout' in scraper:
                config.timeout = int(scraper['timeout'])
            if 'user_agent' in scraper:
                config.user_agent = scraper['user_agent']

        if 'output' in data:
            output = data['output']
            if 'base_dir' in output:
                config.base_dir = Path(output['base_dir'])
            if 'corpus_dir' in output:
                config.corpus_dir = Path(output['corpus_dir'])
            if 'images_dir' in output:
                config.images_dir = Path(output['images_dir'])
            if 'metadata_dir' in output:
                config.metadata_dir = Path(output['metadata_dir'])

        if 'processing' in data:
            proc = data['processing']
            if 'download_images' in proc:
                config.download_images = bool(proc['download_images'])
            if 'max_image_size_mb' in proc:
                config.max_image_size_mb = int(proc['max_image_size_mb'])

        return config


# Default configuration instance
DEFAULT_CONFIG = ScraperConfig()
