"""
Sketch Engine vertical format writer.
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from ..models import Article, Comment
from ..config import ScraperConfig
from .tokeniser import Tokeniser
from .text_cleaner import TextCleaner

logger = logging.getLogger(__name__)


class VerticalWriter:
    """
    Writer for Sketch Engine vertical format (.vert files).

    Produces tokenized output with XML-style structural tags.
    """

    def __init__(self, config: ScraperConfig):
        self.config = config
        self.tokeniser = Tokeniser()
        self.cleaner = TextCleaner()

    def write_article(self, article: Article, output_base_dir: Optional[Path] = None) -> dict:
        """
        Write article and comments to all output formats.

        Args:
            article: Article object with comments
            output_base_dir: Optional base output directory

        Returns:
            Dict with paths to written files
        """
        paths = {}

        if output_base_dir:
            vertical_dir = output_base_dir / "vertical_xml"
            xml_dir = output_base_dir / "xml"
            txt_dir = output_base_dir / "txt"
        else:
            vertical_dir = None
            xml_dir = None
            txt_dir = None

        paths['vertical_xml'] = self.write_article_vertical_xml(article, vertical_dir)
        paths['xml'] = self.write_article_xml(article, xml_dir)
        paths['txt'] = self.write_article_txt(article, txt_dir)

        return paths

    def _get_year_month_dir(self, base_dir: Path, article: Article) -> Path:
        """Get year/month subdirectory path for an article."""
        if article.date_published:
            year = str(article.date_published.year)
            month = f"{article.date_published.month:02d}"
        else:
            year = "unknown"
            month = "00"
        subdir = base_dir / year / month
        subdir.mkdir(parents=True, exist_ok=True)
        return subdir

    def write_article_vertical_xml(self, article: Article, output_dir: Optional[Path] = None) -> str:
        """Write article as SketchEngine vertical XML file."""
        base_dir = output_dir or self.config.vertical_xml_dir
        output_dir = self._get_year_month_dir(base_dir, article)

        filename = f"{article.id}.xml"
        filepath = output_dir / filename

        content = self._article_to_vertical(article)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

        return str(filepath)

    def write_article_xml(self, article: Article, output_dir: Optional[Path] = None) -> str:
        """Write article as standard XML file."""
        base_dir = output_dir or self.config.xml_dir
        output_dir = self._get_year_month_dir(base_dir, article)

        filename = f"{article.id}.xml"
        filepath = output_dir / filename

        content = self._article_to_standard_xml(article)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

        return str(filepath)

    def write_article_txt(self, article: Article, output_dir: Optional[Path] = None) -> str:
        """Write article as plain text file."""
        base_dir = output_dir or self.config.txt_dir
        output_dir = self._get_year_month_dir(base_dir, article)

        filename = f"{article.id}.txt"
        filepath = output_dir / filename

        content = self._article_to_txt(article)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

        return str(filepath)

    def _article_to_txt(self, article: Article) -> str:
        """Convert article to plain text format with preserved comment threading."""
        lines = []

        # Header with metadata
        lines.append("=" * 80)
        lines.append(f"TITLE: {article.title}")
        lines.append(f"AUTHOR: {article.author}")
        if article.date_published:
            lines.append(f"DATE: {article.date_published.strftime('%Y-%m-%d')}")
        lines.append(f"URL: {article.url}")
        if article.categories:
            lines.append(f"CATEGORIES: {', '.join(article.categories)}")
        if article.tags:
            lines.append(f"TAGS: {', '.join(article.tags)}")
        lines.append("=" * 80)
        lines.append("")

        # Article body
        lines.append("ARTICLE CONTENT:")
        lines.append("-" * 40)
        clean_text = self.cleaner.clean(article.content_text)
        lines.append(clean_text)
        lines.append("")

        # Comments section with threaded structure
        if article.comments:
            lines.append("=" * 80)
            lines.append(f"COMMENTS ({len(article.comments)} total):")
            lines.append("=" * 80)
            lines.append("")

            comment_tree = self._build_comment_display_tree(article.comments)

            for comment, display_index, computed_depth, parent_display_idx in comment_tree:
                lines.append(self._comment_to_txt(comment, display_index, computed_depth, parent_display_idx))
                lines.append("")

        return '\n'.join(lines)

    def _build_comment_display_tree(self, comments: list) -> list:
        """
        Build a display-ordered list of comments preserving thread structure.

        Returns:
            List of (comment, display_index, computed_depth, parent_display_index) tuples
        """
        by_id = {c.id: c for c in comments}

        roots = []
        children_map = {}

        for comment in comments:
            parent_id = comment.parent_id

            if parent_id and parent_id in by_id:
                if parent_id not in children_map:
                    children_map[parent_id] = []
                children_map[parent_id].append(comment)
            else:
                roots.append(comment)

        roots.sort(key=lambda c: c.timestamp or datetime.min)

        result = []
        display_index = [0]
        id_to_display_index = {}

        def add_with_children(comment, depth, parent_display_idx):
            display_index[0] += 1
            current_display_idx = display_index[0]
            id_to_display_index[comment.id] = current_display_idx
            result.append((comment, current_display_idx, depth, parent_display_idx))

            children = children_map.get(comment.id, [])
            children.sort(key=lambda c: c.timestamp or datetime.min)

            for child in children:
                add_with_children(child, depth + 1, current_display_idx)

        for root in roots:
            add_with_children(root, 0, None)

        return result

    def _comment_to_txt(self, comment: Comment, index: int, computed_depth: int,
                        parent_display_idx: int = None) -> str:
        """Convert comment to plain text format with visual threading."""
        lines = []

        if computed_depth == 0:
            prefix = ""
            thread_marker = ""
        else:
            prefix = "    " * (computed_depth - 1) + "  |__ "
            if parent_display_idx:
                thread_marker = f"[REPLY to Comment #{parent_display_idx}] "
            else:
                thread_marker = ""

        indent = "    " * computed_depth

        timestamp_str = comment.timestamp.strftime('%Y-%m-%d %H:%M:%S') if comment.timestamp else "Unknown date"

        lines.append(f"{prefix}--- Comment #{index} {thread_marker}---")
        lines.append(f"{indent}[ID]: {comment.id}")
        lines.append(f"{indent}[Author]: {comment.author_name}")
        lines.append(f"{indent}[Date]: {timestamp_str}")
        lines.append(f"{indent}[Depth]: {computed_depth}")
        lines.append(f"{indent}")

        clean_text = self.cleaner.clean(comment.text_clean or comment.text_html)
        for line in clean_text.split('\n'):
            if line.strip():
                lines.append(f"{indent}{line}")

        return '\n'.join(lines)

    def _article_to_standard_xml(self, article: Article) -> str:
        """Convert article to standard XML format string."""
        lines = []

        lines.append('<?xml version="1.0" encoding="UTF-8"?>')

        doc_attrs = self._format_doc_attributes(article)
        lines.append(f'<doc {doc_attrs}>')

        lines.append(f'  <title>{self._escape_xml_content(article.title)}</title>')

        lines.append('  <article>')
        clean_text = self.cleaner.clean(article.content_text)
        paragraphs = self.cleaner.extract_paragraphs(clean_text)

        for para in paragraphs:
            if para.strip():
                lines.append(f'    <p>{self._escape_xml_content(para)}</p>')

        lines.append('  </article>')

        if article.comments:
            lines.append('  <comments>')
            for comment in article.comments:
                comment_xml = self._comment_to_standard_xml(comment)
                lines.append(comment_xml)
            lines.append('  </comments>')

        lines.append('</doc>')

        return '\n'.join(lines)

    def _comment_to_standard_xml(self, comment: Comment) -> str:
        """Convert comment to standard XML format."""
        lines = []

        attrs = self._format_comment_attributes(comment)
        lines.append(f'    <comment {attrs}>')

        clean_text = self.cleaner.clean(comment.text_clean or comment.text_html)
        if clean_text:
            lines.append(f'      <text>{self._escape_xml_content(clean_text)}</text>')

        lines.append('    </comment>')

        return '\n'.join(lines)

    def _escape_xml_content(self, value: str) -> str:
        """Escape string for use in XML content."""
        if not value:
            return ""

        value = str(value)
        value = value.replace('&', '&amp;')
        value = value.replace('<', '&lt;')
        value = value.replace('>', '&gt;')

        return value

    def _article_to_vertical(self, article: Article) -> str:
        """Convert article to vertical format string."""
        lines = []

        doc_attrs = self._format_doc_attributes(article)
        lines.append(f'<doc {doc_attrs}>')

        lines.append('<title>')
        title_tokens = self.tokeniser.tokenize_to_vertical(article.title)
        lines.append(title_tokens)
        lines.append('</title>')

        lines.append('<article>')
        clean_text = self.cleaner.clean(article.content_text)
        paragraphs = self.cleaner.extract_paragraphs(clean_text)

        for para in paragraphs:
            if para.strip():
                lines.append('<p>')
                lines.append(self.tokeniser.tokenize_to_vertical(para))
                lines.append('</p>')

        lines.append('</article>')

        if article.comments:
            lines.append('<comments>')
            for comment in article.comments:
                comment_vertical = self._comment_to_vertical(comment)
                lines.append(comment_vertical)
            lines.append('</comments>')

        lines.append('</doc>')

        return '\n'.join(lines)

    def _format_doc_attributes(self, article: Article) -> str:
        """Format document attributes for opening tag."""
        attrs = []

        attrs.append(f'id="{self._escape_attr(article.id)}"')
        attrs.append(f'url="{self._escape_attr(article.url)}"')
        attrs.append(f'title="{self._escape_attr(article.title)}"')
        attrs.append(f'author="{self._escape_attr(article.author)}"')

        if article.date_published:
            date_str = article.date_published.strftime('%Y-%m-%d')
            attrs.append(f'date="{date_str}"')
            attrs.append(f'year="{article.date_published.year}"')
            attrs.append(f'month="{article.date_published.month:02d}"')
        else:
            attrs.append('date=""')
            attrs.append('year=""')
            attrs.append('month=""')

        categories = '|'.join(self._escape_attr(c) for c in article.categories)
        tags = '|'.join(self._escape_attr(t) for t in article.tags)

        attrs.append(f'categories="{categories}"')
        attrs.append(f'tags="{tags}"')
        attrs.append(f'comment_count="{article.comment_count}"')
        attrs.append('type="article"')

        return ' '.join(attrs)

    def _comment_to_vertical(self, comment: Comment) -> str:
        """Convert comment to vertical format."""
        lines = []

        attrs = self._format_comment_attributes(comment)
        lines.append(f'<comment {attrs}>')

        clean_text = self.cleaner.clean(comment.text_clean or comment.text_html)
        if clean_text:
            lines.append(self.tokeniser.tokenize_to_vertical(clean_text))

        lines.append('</comment>')

        return '\n'.join(lines)

    def _format_comment_attributes(self, comment: Comment) -> str:
        """Format comment attributes for opening tag."""
        attrs = []

        attrs.append(f'id="{self._escape_attr(comment.id)}"')
        attrs.append(f'author="{self._escape_attr(comment.author_name)}"')

        if comment.timestamp:
            date_str = comment.timestamp.strftime('%Y-%m-%d %H:%M:%S')
            attrs.append(f'date="{date_str}"')
        else:
            attrs.append('date=""')

        # Reply structure
        parent_id = comment.parent_id if comment.parent_id else "ROOT"
        attrs.append(f'parent_id="{self._escape_attr(parent_id)}"')
        attrs.append(f'depth="{comment.depth}"')

        # Image information
        has_images = "true" if comment.images else "false"
        attrs.append(f'has_images="{has_images}"')

        if comment.images:
            image_refs = '|'.join(img.filename or img.original_url for img in comment.images)
            attrs.append(f'image_refs="{self._escape_attr(image_refs)}"')
        else:
            attrs.append('image_refs=""')

        return ' '.join(attrs)

    def _escape_attr(self, value: str) -> str:
        """Escape string for use in XML attribute."""
        if not value:
            return ""

        value = str(value)
        value = value.replace('&', '&amp;')
        value = value.replace('<', '&lt;')
        value = value.replace('>', '&gt;')
        value = value.replace('"', '&quot;')
        value = re.sub(r'\s+', ' ', value)

        return value.strip()

    def write_corpus_config(self, output_dir: Optional[Path] = None):
        """Write Sketch Engine corpus configuration file."""
        output_dir = output_dir or self.config.base_dir
        config_path = output_dir / "corpus_config.txt"

        config_content = '''NAME "NoTricksZone Climate Discourse Corpus"
PATH /path/to/corpus
VERTICAL "notrickszone_*.vert"
ENCODING "utf-8"
LANGUAGE "English"
LOCALE "en_GB.UTF-8"

ATTRIBUTE word
ATTRIBUTE lc {
    DYNAMIC lowercase
    DYNLIB internal
    FROMATTR word
    FUNTYPE s
    TRANSQUERY yes
}

STRUCTURE doc {
    ATTRIBUTE id
    ATTRIBUTE url
    ATTRIBUTE title
    ATTRIBUTE author
    ATTRIBUTE date
    ATTRIBUTE year
    ATTRIBUTE month
    ATTRIBUTE categories
    ATTRIBUTE tags
    ATTRIBUTE comment_count
    ATTRIBUTE type
}

STRUCTURE title

STRUCTURE article

STRUCTURE comments

STRUCTURE comment {
    ATTRIBUTE id
    ATTRIBUTE author
    ATTRIBUTE date
    ATTRIBUTE parent_id
    ATTRIBUTE depth
    ATTRIBUTE has_images
    ATTRIBUTE image_refs
}

STRUCTURE p
'''

        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(config_content)

        logger.info(f"Wrote corpus config to {config_path}")

    def generate_stats_report(self, db) -> str:
        """Generate a statistics report."""
        stats = db.get_stats()

        report = f"""
NoTricksZone Scraper Statistics Report
Generated: {datetime.now().isoformat()}
================================

Articles:
  Total discovered: {stats['total_articles']}
  By status:
"""
        for status, count in stats.get('articles_by_status', {}).items():
            report += f"    {status}: {count}\n"

        report += f"""
Comments:
  Total scraped: {stats['total_comments']}

Images:
  Total found: {stats['total_images']}
  Downloaded: {stats['downloaded_images']}
"""

        return report
