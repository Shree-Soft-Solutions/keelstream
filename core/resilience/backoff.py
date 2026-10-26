"""
Exponential Backoff and Retry-After parsing implementation for KeelStream.
Implements AWS Architecture best practices (Full Jitter, Equal Jitter, Decorrelated Jitter).
"""

import math
import random
import time
from email.utils import parsedate_to_datetime
from typing import Optional, Union


def parse_retry_after(header_val: Optional[Union[str, int, float]]) -> Optional[float]:
    """
    Parses standard HTTP Retry-After header.
    Can be integer seconds (e.g., '120') or HTTP-Date format (RFC 7231).
    Returns delay in seconds, or None if invalid/missing.
    """
    if header_val is None:
        return None

    if isinstance(header_val, (int, float)):
        return max(0.0, float(header_val))

    val_str = str(header_val).strip()
    if not val_str:
        return None

    # Check if numeric seconds
    try:
        seconds = float(val_str)
        return max(0.0, seconds)
    except ValueError:
        pass

    # Attempt to parse HTTP-date format
    try:
        target_dt = parsedate_to_datetime(val_str)
        now_ts = time.time()
        target_ts = target_dt.timestamp()
        delay = target_ts - now_ts
        return max(0.0, delay)
    except Exception:
        return None


class ExponentialBackoff:
    """
    Calculates exponential backoff delay with jitter to prevent the thundering herd problem.
    """

    def __init__(
        self,
        base_delay: float = 0.5,
        max_delay: float = 30.0,
        multiplier: float = 2.0,
        jitter: bool = True,
        jitter_mode: str = "full",  # "full", "equal", "decorrelated", "none"
    ):
        if base_delay <= 0:
            raise ValueError("base_delay must be strictly positive.")
        if max_delay < base_delay:
            raise ValueError("max_delay cannot be less than base_delay.")
        if multiplier < 1.0:
            raise ValueError("multiplier must be >= 1.0.")

        self.base_delay = base_delay
        self.max_delay = max_delay
        self.multiplier = multiplier
        self.jitter = jitter
        self.jitter_mode = jitter_mode.lower()
        self._prev_sleep = base_delay

    def compute_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        """
        Computes the sleep duration for the given 0-indexed attempt.
        If retry_after is provided, it is respected while keeping within max_delay safety bounds.
        """
        if retry_after is not None and retry_after >= 0:
            return min(self.max_delay, float(retry_after))

        attempt = max(0, attempt)
        raw_delay = min(self.max_delay, self.base_delay * (self.multiplier ** attempt))

        if not self.jitter or self.jitter_mode == "none":
            self._prev_sleep = raw_delay
            return raw_delay

        if self.jitter_mode == "full":
            delay = random.uniform(0, raw_delay)
        elif self.jitter_mode == "equal":
            half = raw_delay / 2.0
            delay = half + random.uniform(0, half)
        elif self.jitter_mode == "decorrelated":
            delay = min(self.max_delay, random.uniform(self.base_delay, self._prev_sleep * 3.0))
        else:
            delay = random.uniform(0, raw_delay)

        self._prev_sleep = delay
        return delay

    def reset(self) -> None:
        """Resets stateful jitter trackers."""
        self._prev_sleep = self.base_delay
