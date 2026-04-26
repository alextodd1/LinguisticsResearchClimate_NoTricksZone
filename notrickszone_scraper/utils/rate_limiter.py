"""
Rate limiting for polite scraping.
"""

import time
import threading
from typing import Optional


class RateLimiter:
    """Thread-safe rate limiter with configurable delay."""

    def __init__(self, delay: float = 0.2):
        """
        Initialize rate limiter.

        Args:
            delay: Minimum seconds between requests
        """
        self.delay = delay
        self._last_request: Optional[float] = None
        self._lock = threading.Lock()

    def wait(self):
        """Wait if necessary to maintain rate limit."""
        with self._lock:
            if self._last_request is not None:
                elapsed = time.time() - self._last_request
                if elapsed < self.delay:
                    sleep_time = self.delay - elapsed
                    time.sleep(sleep_time)
            self._last_request = time.time()

    def set_delay(self, delay: float):
        """Update the delay (e.g., for exponential backoff)."""
        with self._lock:
            self.delay = delay
