"""
HTML parsing for NoTricksZone articles and comments.
"""

import re
import json
import logging
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse
from datetime import datetime

from bs4 import BeautifulSoup, Tag
import html as html_module

from ..models import Article, Comment, ImageRef, ArticleStub
from .date_parser import parse_date, parse_wordpress_date

logger = logging.getLogger(__name__)


class ArticleParser:
    """Parser for NoTricksZone article pages."""

    def __init__(self, base_url: str = "https://notrickszone.com"):
        self.base_url = base_url

    def parse_article(self, html_content: str, url: str) -> Article:
        """
        Parse a full article page.

        Args:
            html_content: HTML content of article page
            url: URL of the article

        Returns:
            Article object
        """
        soup = BeautifulSoup(html_content, 'lxml')

        # Try to extract JSON-LD structured data first
        json_ld = self._extract_json_ld(soup)

        # Extract article ID from URL
        article_id = self._extract_article_id(url, soup)

        # Title
        title = self._extract_title(soup, json_ld)

        # Author
        author = self._extract_author(soup, json_ld)

        # Date
        date_published = self._extract_date(soup, url, json_ld)

        # Categories and tags
        categories = self._extract_categories(soup)
        tags = self._extract_tags(soup)

        # Content
        content_html, content_text = self._extract_content(soup)

        # Comment count
        comment_count = self._extract_comment_count(soup, json_ld)

        return Article(
            id=article_id,
            url=url,
            title=title,
            author=author,
            date_published=date_published,
            categories=categories,
            tags=tags,
            content_html=content_html,
            content_text=content_text,
            comment_count=comment_count,
            scraped_at=datetime.now()
        )

    def _extract_json_ld(self, soup: BeautifulSoup) -> Optional[dict]:
        """Extract JSON-LD structured data from page."""
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string)
                # Handle both single object and array
                if isinstance(data, list):
                    for item in data:
                        if item.get('@type') in ('Article', 'NewsArticle', 'BlogPosting'):
                            return item
                elif isinstance(data, dict):
                    if data.get('@type') in ('Article', 'NewsArticle', 'BlogPosting'):
                        return data
                    # Check @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if isinstance(item, dict) and item.get('@type') in ('Article', 'NewsArticle', 'BlogPosting'):
                                return item
            except (json.JSONDecodeError, TypeError):
                continue
        return None

    def _extract_article_id(self, url: str, soup: BeautifulSoup = None) -> str:
        """Extract article ID from URL, prefixed with date if available."""
        parsed = urlparse(url)
        path = parsed.path.strip('/')

        # Remove any trailing segments like page numbers
        slug = path.split('/')[-1] if path else ''

        if not slug:
            import hashlib
            return hashlib.md5(url.encode()).hexdigest()[:12]

        # Try to get date to prefix the slug
        if soup:
            date = self._extract_date(soup, url)
            if date:
                return f"{date.strftime('%Y%m%d')}_{slug}"

        return slug

    def _extract_title(self, soup: BeautifulSoup, json_ld: dict = None) -> str:
        """Extract article title."""
        # Try JSON-LD first
        if json_ld and json_ld.get('headline'):
            return json_ld['headline']

        selectors = [
            'h1.entry-title',
            'h1.post-title',
            'article h1',
            '.entry-header h1',
            'h1',
        ]

        for selector in selectors:
            elem = soup.select_one(selector)
            if elem:
                return elem.get_text(strip=True)

        # Try meta tag
        meta = soup.select_one('meta[property="og:title"]')
        if meta:
            return meta.get('content', '')

        return ""

    def _extract_author(self, soup: BeautifulSoup, json_ld: dict = None) -> str:
        """Extract author name."""
        # Try JSON-LD first
        if json_ld:
            author = json_ld.get('author')
            if isinstance(author, dict):
                name = author.get('name', '')
                if name:
                    return name
            elif isinstance(author, str):
                return author

        # Try meta tag
        meta = soup.select_one('meta[name="author"]')
        if meta and meta.get('content'):
            return meta.get('content', '')

        selectors = [
            '.author a',
            '.entry-author a',
            '.post-author a',
            'a[rel="author"]',
            '.byline a',
            '.author-name',
        ]

        for selector in selectors:
            elem = soup.select_one(selector)
            if elem:
                return elem.get_text(strip=True)

        # Look for "Written by Author" pattern
        for elem in soup.select('.entry-meta, .post-meta, .byline, p'):
            text = elem.get_text()
            match = re.search(r'(?:Written by|By)\s+(.+?)(?:\s*\||$)', text, re.I)
            if match:
                author = match.group(1).strip()
                # Clean up - remove date strings that might follow
                author = re.sub(r'\s*(?:on\s+\w+\s+\d+.*|Published.*)$', '', author, flags=re.I)
                if author and len(author) < 100:
                    return author

        return "Unknown"

    def _extract_date(self, soup: BeautifulSoup, url: str, json_ld: dict = None) -> Optional[datetime]:
        """Extract publication date."""
        # Try JSON-LD first
        if json_ld:
            date_str = json_ld.get('datePublished') or json_ld.get('dateCreated')
            if date_str:
                dt = parse_wordpress_date(date_str)
                if dt:
                    return dt

        # Try datetime attribute
        time_elem = soup.select_one('time[datetime]')
        if time_elem:
            dt = parse_wordpress_date(time_elem.get('datetime', ''))
            if dt:
                return dt

        # Try meta tags
        meta_selectors = [
            'meta[property="article:published_time"]',
            'meta[property="og:published_time"]',
            'meta[name="date"]',
        ]

        for selector in meta_selectors:
            meta = soup.select_one(selector)
            if meta:
                dt = parse_wordpress_date(meta.get('content', ''))
                if dt:
                    return dt

        # Try visible date elements
        date_selectors = [
            '.entry-date',
            '.post-date',
            '.published',
            'time.entry-date',
        ]

        for selector in date_selectors:
            elem = soup.select_one(selector)
            if elem:
                dt = parse_date(elem.get_text(strip=True))
                if dt:
                    return dt

        # Look for "Published on Month DD, YYYY" pattern
        for elem in soup.select('.entry-meta, .post-meta, p'):
            text = elem.get_text()
            match = re.search(r'Published\s+on\s+(\w+\s+\d{1,2},?\s+\d{4})', text, re.I)
            if match:
                dt = parse_date(match.group(1))
                if dt:
                    return dt

        # Extract from URL if date pattern present
        match = re.search(r'/(\d{4})/(\d{2})/(\d{2})/', url)
        if match:
            try:
                return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                pass

        return None

    def _extract_categories(self, soup: BeautifulSoup) -> List[str]:
        """Extract article categories from metadata area only."""
        categories = []

        # Work on a copy to avoid modifying the original soup
        from copy import copy
        article = soup.select_one('article.post, article.type-post, .hentry, .single-post')

        if article:
            article = copy(article)
            # Remove related/recommended sections
            for related in article.select('.yarpp-related, .related-posts, .jp-relatedposts, '
                                          '.recommended-posts, .related, .sharedaddy'):
                related.decompose()

            # Look for categories in article metadata areas
            meta_areas = article.select('.entry-meta, .post-meta, .cat-links, .entry-categories, '
                                        '.entry-header, .entry-footer')

            for meta in meta_areas:
                for link in meta.select('a[href*="/category/"]'):
                    cat = link.get_text(strip=True)
                    if cat and cat not in categories:
                        categories.append(cat)

        # Fallback: look for category links anywhere in header area
        if not categories:
            header = soup.select_one('.entry-header, .post-header, header.entry-header')
            if header:
                for link in header.select('a[href*="/category/"]'):
                    cat = link.get_text(strip=True)
                    if cat and cat not in categories:
                        categories.append(cat)

        # Fallback: try all category links on page (not in comments or related)
        if not categories:
            for link in soup.select('a[href*="/category/"]'):
                # Skip links inside comments section
                if link.find_parent(id='comments'):
                    continue
                cat = link.get_text(strip=True)
                if cat and cat not in categories and len(cat) < 50:
                    categories.append(cat)

        return categories

    def _extract_tags(self, soup: BeautifulSoup) -> List[str]:
        """Extract article tags from metadata area only."""
        tags = []

        # NoTricksZone (and many older WP themes) put rel="tag" on *category*
        # links too. Match only links whose href contains /tag/ to avoid
        # picking up categories — never trust rel="tag" alone here.
        def _is_real_tag_link(link) -> bool:
            href = (link.get('href') or '').lower()
            if '/tag/' not in href:
                return False
            if '/category/' in href:
                return False
            return True

        from copy import copy
        article = soup.select_one('article.post, article.type-post, .hentry, .single-post')

        if article:
            article = copy(article)
            for related in article.select('.yarpp-related, .related-posts, .jp-relatedposts, '
                                          '.recommended-posts, .related, .sharedaddy'):
                related.decompose()

            meta_areas = article.select('.entry-meta, .post-meta, .tag-links, .entry-tags, '
                                        '.entry-header, .entry-footer')

            for meta in meta_areas:
                for link in meta.find_all('a'):
                    if not _is_real_tag_link(link):
                        continue
                    tag = link.get_text(strip=True)
                    if tag and tag not in tags:
                        tags.append(tag)

        if not tags:
            for container in soup.select('.entry-footer .tag-links, .post-footer .tag-links'):
                for link in container.find_all('a'):
                    if not _is_real_tag_link(link):
                        continue
                    tag = link.get_text(strip=True)
                    if tag and tag not in tags:
                        tags.append(tag)

        return tags

    def _extract_content(self, soup: BeautifulSoup) -> Tuple[str, str]:
        """Extract article content as HTML and clean text."""
        selectors = [
            '.entry-content',
            'article .content',
            '.post-content',
            '.article-content',
            'article',
        ]

        content_elem = None
        for selector in selectors:
            elem = soup.select_one(selector)
            if elem:
                content_elem = elem
                break

        if not content_elem:
            return "", ""

        # Remove unwanted elements
        for unwanted in content_elem.select(
            'script, style, .sharedaddy, .jp-relatedposts, .comments, #comments, '
            '.essb_links, .essb-links, .social-sharing, .post-share'
        ):
            unwanted.decompose()

        content_html = str(content_elem)
        content_text = self._clean_text(content_elem.get_text(separator='\n'))

        return content_html, content_text

    def _extract_comment_count(self, soup: BeautifulSoup, json_ld: dict = None) -> int:
        """Extract comment count from page."""
        # Try JSON-LD first
        if json_ld and json_ld.get('commentCount'):
            try:
                return int(json_ld['commentCount'])
            except (ValueError, TypeError):
                pass

        # Count actual comment elements on page (native-WP uses li.comment;
        # we check both shapes for robustness across themes).
        comments = soup.select('li.comment[id^="comment-"], li[id^="comment-"]')
        if comments:
            return len(comments)

        # Try comment count text
        selectors = [
            '.comments-link',
            '.comment-count',
            '#comments h2',
            '#comments h3',
        ]

        for selector in selectors:
            elem = soup.select_one(selector)
            if elem:
                text = elem.get_text()
                match = re.search(r'(\d+)\s*(?:comments?|responses?)', text, re.I)
                if match:
                    return int(match.group(1))

        return 0

    def _clean_text(self, text: str) -> str:
        """Clean extracted text."""
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\n\s*\n', '\n\n', text)
        return text.strip()


class CommentParser:
    """
    Parser for native WordPress comments on NoTricksZone.

    Native-WP structure (the markup WordPress core ships out of the box):
    - Container: ol.commentlist (older themes) or ol.comment-list (newer themes)
    - Each comment: <li id="comment-NNNNN" class="comment ..."> ...
    - Replies are nested in a child <ol class="children"> inside the parent <li>
    - Author: cite.fn or .comment-author .fn (sometimes wrapped in <a>)
    - Date: a <time datetime="..."> element inside .comment-meta, or the <a>
            inside .comment-meta whose text is a human date (e.g.
            "24. April 2026 at 3:30 pm" — NTZ uses German month names because
            P Gosselin posts from Germany)
    - Body: .comment-content or paragraphs inside .comment-body (after the
            comment-author / comment-meta blocks; the reply link is excluded)
    """

    def __init__(self, base_url: str = "https://notrickszone.com"):
        self.base_url = base_url

    def parse_comments(self, html_content: str, article_url: str) -> List[Comment]:
        """Parse all comments from article page, preserving thread structure."""
        soup = BeautifulSoup(html_content, 'lxml')
        comments: List[Comment] = []

        comment_list = soup.select_one(
            'ol.comment-list, ol.commentlist, '
            '#comments ol.comment-list, #comments ol.commentlist, '
            'ul.comment-list, ul.commentlist'
        )

        if not comment_list:
            comments_div = soup.find(id='comments') or soup.select_one('.comments-area')
            if comments_div:
                comment_list = comments_div.find(['ol', 'ul'])

        if not comment_list:
            logger.debug(f"No comment list found for {article_url}")
            return comments

        self._parse_comment_list(comment_list, article_url, comments, parent_id=None, depth=0)
        logger.debug(f"Parsed {len(comments)} comments from {article_url}")
        return comments

    def _parse_comment_list(self, list_elem: Tag, article_url: str,
                             comments: List[Comment], parent_id: Optional[str],
                             depth: int):
        """
        Each <li class="comment" id="comment-N"> in `list_elem` is one comment.
        Replies live in a nested <ol class="children"> (or <ul class="children">)
        inside that same <li>.
        """
        for li in list_elem.find_all('li', recursive=False):
            li_classes = ' '.join(li.get('class', []) or [])
            li_id = li.get('id', '') or ''

            # Skip <li> elements that aren't actual comments (some themes inject
            # pingback/trackback or pagination li's into the same list).
            if 'comment' not in li_classes and not li_id.startswith('comment-'):
                # Still recurse children in case markup nests unexpectedly
                inner = li.find(['ol', 'ul'], recursive=False)
                if inner:
                    self._parse_comment_list(inner, article_url, comments, parent_id, depth)
                continue

            comment = self._parse_single_comment(li, article_url, parent_id, depth)
            if comment:
                comments.append(comment)

                children_list = (
                    li.find('ol', class_='children', recursive=False)
                    or li.find('ul', class_='children', recursive=False)
                )
                if children_list:
                    self._parse_comment_list(
                        children_list, article_url, comments,
                        parent_id=comment.id, depth=depth + 1
                    )

    def _parse_single_comment(self, li: Tag, article_url: str,
                               parent_id: Optional[str] = None,
                               depth: int = 0) -> Optional[Comment]:
        """Parse one <li class="comment" id="comment-NNNNN"> element."""
        try:
            comment_id = li.get('id', '') or ''
            # Strip any prefix like "div-comment-" some themes add
            m = re.search(r'comment-(\d+)', comment_id)
            if m:
                comment_id = f"comment-{m.group(1)}"
            else:
                import hashlib
                content_hash = hashlib.md5(li.get_text()[:100].encode()).hexdigest()[:8]
                comment_id = f"comment-{content_hash}"

            # The .comment-body is what we work with for author / meta / text;
            # for nested comments, scope to the immediate body so we don't pick
            # up replies' fields.
            body = li.find(['div', 'article'], class_=re.compile(r'comment-body'), recursive=False)
            if not body:
                # Some themes nest the body one level deeper or put fields directly on <li>
                body = li.find(['div', 'article'], class_=re.compile(r'comment-body'))
            scope = body if body else li

            # ---- Author ----
            author_name = "Anonymous"
            author_url: Optional[str] = None

            author_root = (
                scope.select_one('.comment-author .fn')
                or scope.select_one('cite.fn')
                or scope.select_one('.comment-author')
                or scope.select_one('.fn')
            )
            if author_root:
                # Inside .fn there's often an <a> with the homepage URL
                a = author_root.find('a')
                if a:
                    author_name = a.get_text(strip=True) or author_name
                    href = a.get('href')
                    if href:
                        author_url = href
                else:
                    author_name = author_root.get_text(strip=True) or author_name

            # ---- Timestamp ----
            timestamp = None
            time_elem = scope.select_one('.comment-meta time[datetime], time[datetime]')
            if time_elem:
                timestamp = parse_wordpress_date(time_elem.get('datetime', ''))

            if not timestamp:
                # Fallback: visible text of the comment-meta link
                meta_link = scope.select_one('.comment-meta a, .commentmetadata a')
                if meta_link:
                    text = meta_link.get_text(' ', strip=True)
                    text = re.sub(r'\s*\|\s*.*$', '', text)
                    timestamp = parse_wordpress_date(text)

            if not timestamp:
                meta_text_elem = scope.select_one('.comment-meta, .commentmetadata')
                if meta_text_elem:
                    text = meta_text_elem.get_text(' ', strip=True)
                    timestamp = parse_wordpress_date(text)

            # ---- Body text ----
            text_parts: List[str] = []
            text_html_parts: List[str] = []

            content = scope.select_one('.comment-content')
            if content:
                for child in content.find_all(['p', 'blockquote'], recursive=False):
                    txt = child.get_text(separator=' ', strip=True)
                    if txt:
                        text_parts.append(txt)
                        text_html_parts.append(str(child))
                if not text_parts:
                    txt = content.get_text(separator=' ', strip=True)
                    if txt:
                        text_parts.append(txt)
                        text_html_parts.append(str(content))
            else:
                # Native WP without .comment-content: paragraphs sit directly in
                # .comment-body, alongside .comment-author / .comment-meta / .reply.
                # Walk direct children, skipping the metadata sub-blocks and the
                # reply link.
                for child in scope.find_all(['p', 'blockquote'], recursive=False):
                    cls = ' '.join(child.get('class', []) or [])
                    if any(skip in cls for skip in ('comment-author', 'comment-meta',
                                                     'commentmetadata', 'reply')):
                        continue
                    if child.find(class_='comment-reply-link'):
                        continue
                    txt = child.get_text(separator=' ', strip=True)
                    if txt:
                        text_parts.append(txt)
                        text_html_parts.append(str(child))

            # Last-resort fallback: everything in scope minus known non-content blocks
            if not text_parts:
                from copy import copy
                clone = copy(scope)
                for unwanted in clone.select(
                    '.comment-author, .comment-meta, .commentmetadata, '
                    '.reply, .comment-reply-link'
                ):
                    unwanted.decompose()
                text = clone.get_text(separator=' ', strip=True)
                text = re.sub(r'\s+', ' ', text).strip()
                if text:
                    text_parts.append(text)
                    text_html_parts.append(str(clone))

            text_clean = ' '.join(text_parts).strip()
            text_html = ' '.join(text_html_parts)

            images = self._parse_images(scope, article_url, comment_id)

            if not text_clean and author_name == "Anonymous":
                return None

            return Comment(
                id=comment_id,
                article_id=article_url,
                author_name=author_name,
                author_url=author_url,
                timestamp=timestamp or datetime.now(),
                text_html=text_html,
                text_clean=text_clean,
                parent_id=parent_id,
                depth=depth,
                images=images
            )

        except Exception as e:
            logger.error(f"Error parsing comment: {e}", exc_info=True)
            return None

    def _parse_images(self, elem: Tag, article_url: str, comment_id: str) -> List[ImageRef]:
        """Extract image references from comment body (skip avatars)."""
        images: List[ImageRef] = []
        if not elem:
            return images

        for img in elem.select('img'):
            classes = ' '.join(img.get('class', []) or [])
            if 'avatar' in classes:
                continue
            src = img.get('src') or img.get('data-src')
            if src:
                if not src.startswith('http'):
                    src = urljoin(self.base_url, src)
                images.append(ImageRef(original_url=src))

        for link in elem.select('a[href]'):
            href = link.get('href', '')
            if re.search(r'\.(jpg|jpeg|png|gif|webp)(\?|$)', href, re.I):
                if not href.startswith('http'):
                    href = urljoin(self.base_url, href)
                if not any(img.original_url == href for img in images):
                    images.append(ImageRef(original_url=href))

        return images
