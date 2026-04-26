"""
Text cleaning and normalization utilities.
"""

import re
import html
from typing import Optional
import unicodedata


class TextCleaner:
    """Clean and normalize text for corpus output."""

    # Common HTML entities that might slip through
    HTML_ENTITIES = {
        '&nbsp;': ' ',
        '&amp;': '&',
        '&lt;': '<',
        '&gt;': '>',
        '&quot;': '"',
        '&apos;': "'",
        '&mdash;': '\u2014',
        '&ndash;': '\u2013',
        '&hellip;': '\u2026',
        '&rsquo;': "'",
        '&lsquo;': "'",
        '&rdquo;': '"',
        '&ldquo;': '"',
    }

    # Patterns to remove
    REMOVE_PATTERNS = [
        r'<script[^>]*>.*?</script>',
        r'<style[^>]*>.*?</style>',
        r'<!--.*?-->',
        r'<[^>]+>',  # HTML tags
    ]

    def __init__(self):
        # Compile patterns for efficiency
        self.remove_patterns = [
            re.compile(p, re.IGNORECASE | re.DOTALL)
            for p in self.REMOVE_PATTERNS
        ]

    def clean(self, text: str) -> str:
        """
        Clean text for output.

        Args:
            text: Raw text (may contain HTML remnants)

        Returns:
            Cleaned text
        """
        if not text:
            return ""

        # Remove HTML tags and scripts
        for pattern in self.remove_patterns:
            text = pattern.sub(' ', text)

        # Decode HTML entities
        text = html.unescape(text)

        # Handle remaining named entities
        for entity, replacement in self.HTML_ENTITIES.items():
            text = text.replace(entity, replacement)

        # Normalize unicode
        text = unicodedata.normalize('NFKC', text)

        # Replace various dash/hyphen characters with standard ones
        text = re.sub(r'[\u2014\u2013\u2212]', '-', text)

        # Normalize quotes
        text = re.sub(r'[\u201c\u201d\u201e]', '"', text)
        text = re.sub(r'[\u2018\u2019\u201a]', "'", text)

        # Normalize whitespace
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n\s*\n', '\n\n', text)

        # Remove control characters (except newlines and tabs)
        text = ''.join(
            char for char in text
            if unicodedata.category(char) != 'Cc' or char in '\n\t'
        )

        return text.strip()

    def clean_for_vertical(self, text: str) -> str:
        """
        Clean text specifically for vertical format output.

        Escape special XML characters but preserve structure.

        Args:
            text: Text to clean

        Returns:
            Cleaned text safe for vertical format
        """
        text = self.clean(text)

        # Escape XML special characters
        text = text.replace('&', '&amp;')
        text = text.replace('<', '&lt;')
        text = text.replace('>', '&gt;')

        return text

    def extract_paragraphs(self, text: str) -> list:
        """
        Split text into paragraphs.

        Args:
            text: Full text content

        Returns:
            List of paragraph strings
        """
        text = self.clean(text)

        # Split on double newlines
        paragraphs = re.split(r'\n\s*\n', text)

        # Filter empty paragraphs
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        return paragraphs

    def normalize_url(self, url: str) -> str:
        """
        Normalize a URL for consistent storage.

        Args:
            url: URL to normalize

        Returns:
            Normalized URL
        """
        if not url:
            return ""

        # Remove trailing slashes for consistency
        url = url.rstrip('/')

        # Ensure https
        if url.startswith('http://'):
            url = 'https://' + url[7:]

        return url

    def truncate(self, text: str, max_length: int = 200) -> str:
        """
        Truncate text to maximum length, breaking at word boundary.

        Args:
            text: Text to truncate
            max_length: Maximum length

        Returns:
            Truncated text with ellipsis if needed
        """
        if len(text) <= max_length:
            return text

        # Find last space before limit
        truncated = text[:max_length]
        last_space = truncated.rfind(' ')

        if last_space > max_length * 0.5:
            truncated = truncated[:last_space]

        return truncated.strip() + '...'
