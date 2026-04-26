"""
Date parsing utilities for various formats.
"""

import re
from datetime import datetime, timedelta
from typing import Optional
import logging

from dateutil import parser as date_parser
from dateutil.tz import tzutc

logger = logging.getLogger(__name__)

# NoTricksZone author P Gosselin posts dates in German.
# Native WordPress also still localises month names in some themes.
GERMAN_MONTHS = {
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4,
    "mai": 5, "juni": 6, "juli": 7, "august": 8, "september": 9,
    "oktober": 10, "november": 11, "dezember": 12,
}


def parse_german_date(date_str: str) -> Optional[datetime]:
    """
    Parse German-formatted dates like:
        "24. April 2026"
        "24. April 2026 at 3:30 pm"
        "24. April 2026 um 15:30"

    Returns datetime or None if no German pattern matched.
    """
    if not date_str:
        return None

    # Day. Month YYYY  (with optional time after "at"/"um")
    m = re.search(
        r'(\d{1,2})\.\s*([A-Za-zÄÖÜäöüß]+)\s*(\d{4})'
        r'(?:\s+(?:at|um)\s+(\d{1,2}):(\d{2})(?:\s*(am|pm))?)?',
        date_str,
        re.IGNORECASE,
    )
    if not m:
        return None

    day = int(m.group(1))
    month_name = m.group(2).lower()
    month = GERMAN_MONTHS.get(month_name)
    if not month:
        return None
    year = int(m.group(3))

    hour = 0
    minute = 0
    if m.group(4) and m.group(5):
        hour = int(m.group(4))
        minute = int(m.group(5))
        ampm = (m.group(6) or '').lower()
        if ampm == 'pm' and hour < 12:
            hour += 12
        elif ampm == 'am' and hour == 12:
            hour = 0

    try:
        return datetime(year, month, day, hour, minute)
    except ValueError:
        return None


def parse_date(date_str: str) -> Optional[datetime]:
    """
    Parse a date string in various formats.

    Args:
        date_str: Date string to parse

    Returns:
        datetime object or None if parsing failed
    """
    if not date_str:
        return None

    date_str = date_str.strip()

    # Try relative date first
    relative = parse_relative_date(date_str)
    if relative:
        return relative

    # Try German format before falling through to dateutil — dateutil's English
    # locale will reject "24. April 2026" with German month spellings.
    german = parse_german_date(date_str)
    if german:
        return german

    # Try standard parsing
    try:
        dt = date_parser.parse(date_str, fuzzy=True)
        # Remove timezone if present for consistency
        if dt.tzinfo:
            dt = dt.replace(tzinfo=None)
        return dt
    except (ValueError, TypeError) as e:
        logger.debug(f"Could not parse date '{date_str}': {e}")
        return None


def parse_relative_date(date_str: str) -> Optional[datetime]:
    """
    Parse relative date strings like "5 hours ago", "2 days ago".

    Args:
        date_str: Relative date string

    Returns:
        datetime object or None if not a relative date
    """
    if not date_str:
        return None

    date_str = date_str.strip().lower()
    now = datetime.now()

    # Patterns for relative dates
    patterns = [
        (r'(\d+)\s*seconds?\s*ago', lambda m: now - timedelta(seconds=int(m.group(1)))),
        (r'(\d+)\s*minutes?\s*ago', lambda m: now - timedelta(minutes=int(m.group(1)))),
        (r'(\d+)\s*hours?\s*ago', lambda m: now - timedelta(hours=int(m.group(1)))),
        (r'(\d+)\s*days?\s*ago', lambda m: now - timedelta(days=int(m.group(1)))),
        (r'(\d+)\s*weeks?\s*ago', lambda m: now - timedelta(weeks=int(m.group(1)))),
        (r'(\d+)\s*months?\s*ago', lambda m: now - timedelta(days=int(m.group(1)) * 30)),
        (r'(\d+)\s*years?\s*ago', lambda m: now - timedelta(days=int(m.group(1)) * 365)),
        (r'just now', lambda m: now),
        (r'a minute ago', lambda m: now - timedelta(minutes=1)),
        (r'an hour ago', lambda m: now - timedelta(hours=1)),
        (r'a day ago', lambda m: now - timedelta(days=1)),
        (r'yesterday', lambda m: now - timedelta(days=1)),
        (r'a week ago', lambda m: now - timedelta(weeks=1)),
        (r'a month ago', lambda m: now - timedelta(days=30)),
        (r'a year ago', lambda m: now - timedelta(days=365)),
    ]

    for pattern, converter in patterns:
        match = re.search(pattern, date_str)
        if match:
            try:
                return converter(match)
            except Exception:
                continue

    return None


def parse_wordpress_date(date_str: str) -> Optional[datetime]:
    """
    Parse WordPress-style date formats.

    Common formats:
    - "January 20, 2017"
    - "2017-01-20"
    - "2017-01-20T15:30:00+00:00"
    - "February 12, 2026 at 1:38 pm"
    """
    if not date_str:
        return None

    date_str = date_str.strip()

    # Strip trailing " | #" markers some WP themes append to comment dates
    date_str = re.sub(r'\s*\|\s*#?\s*$', '', date_str)

    # Common WordPress formats
    formats = [
        "%Y-%m-%dT%H:%M:%S%z",       # ISO with timezone
        "%Y-%m-%dT%H:%M:%S",         # ISO without timezone
        "%Y-%m-%d %H:%M:%S",         # SQL-style
        "%Y-%m-%d",                   # Date only
        "%B %d, %Y at %I:%M %p",     # "February 12, 2026 at 1:38 pm"
        "%B %d, %Y at %I:%M%p",      # "February 12, 2026 at 1:38pm"
        "%B %d, %Y",                 # "January 20, 2017"
        "%b %d, %Y",                 # "Jan 20, 2017"
        "%d %B %Y",                  # "20 January 2017"
        "%d %b %Y",                  # "20 Jan 2017"
        "%m/%d/%Y",                  # US format
        "%d/%m/%Y",                  # EU format
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            if dt.tzinfo:
                dt = dt.replace(tzinfo=None)
            return dt
        except ValueError:
            continue

    # Try German format before generic dateutil
    german = parse_german_date(date_str)
    if german:
        return german

    # Fall back to dateutil
    return parse_date(date_str)


def format_date_for_output(dt: datetime, include_time: bool = True) -> str:
    """
    Format datetime for output.

    Args:
        dt: datetime object
        include_time: Whether to include time component

    Returns:
        Formatted date string
    """
    if not dt:
        return ""

    if include_time:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    else:
        return dt.strftime("%Y-%m-%d")
