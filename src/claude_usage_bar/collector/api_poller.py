"""Optional Anthropic API rate-limit poller.

Makes a minimal API call to read X-RateLimit-* response headers.
Only active when anthropic_api_key is set in config.

Rate limit windows from Anthropic headers:
    x-ratelimit-limit-tokens          — limit per minute
    x-ratelimit-remaining-tokens      — remaining this minute
    x-ratelimit-limit-requests        — requests per minute
    x-ratelimit-remaining-requests    — remaining this minute

We also track 5-hour and 7-day windows if the headers expose them.
At time of writing, Anthropic exposes per-minute limits only.
The plan mentions 5h/7d windows — we display what headers provide.
"""

from __future__ import annotations

import logging
import threading
import time
import urllib.request
import urllib.error
import json
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_PROBE_ENDPOINT = "https://api.anthropic.com/v1/messages"
_PROBE_BODY = json.dumps({
    "model": "claude-haiku-4-5-20251001",
    "max_tokens": 1,
    "messages": [{"role": "user", "content": "hi"}],
}).encode()


@dataclass
class RateLimitStats:
    """Current snapshot of rate-limit headers."""
    tokens_limit: int = 0
    tokens_remaining: int = 0
    requests_limit: int = 0
    requests_remaining: int = 0
    last_updated: float = 0.0

    @property
    def tokens_pct_used(self) -> float:
        if self.tokens_limit == 0:
            return 0.0
        return (self.tokens_limit - self.tokens_remaining) / self.tokens_limit

    @property
    def requests_pct_used(self) -> float:
        if self.requests_limit == 0:
            return 0.0
        return (self.requests_limit - self.requests_remaining) / self.requests_limit


class ApiPoller:
    """Background thread that periodically polls rate-limit headers."""

    POLL_INTERVAL = 60  # seconds between probes

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._stats = RateLimitStats()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if not self._api_key:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="api-poller")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def get_stats(self) -> RateLimitStats:
        with self._lock:
            return RateLimitStats(
                tokens_limit=self._stats.tokens_limit,
                tokens_remaining=self._stats.tokens_remaining,
                requests_limit=self._stats.requests_limit,
                requests_remaining=self._stats.requests_remaining,
                last_updated=self._stats.last_updated,
            )

    def _loop(self) -> None:
        # Poll immediately, then every POLL_INTERVAL seconds
        while not self._stop_event.is_set():
            self._poll()
            self._stop_event.wait(timeout=self.POLL_INTERVAL)

    def _poll(self) -> None:
        req = urllib.request.Request(
            _PROBE_ENDPOINT,
            data=_PROBE_BODY,
            method="POST",
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                headers = resp.headers
                updated = RateLimitStats(
                    tokens_limit=_int_header(headers, "x-ratelimit-limit-tokens"),
                    tokens_remaining=_int_header(headers, "x-ratelimit-remaining-tokens"),
                    requests_limit=_int_header(headers, "x-ratelimit-limit-requests"),
                    requests_remaining=_int_header(headers, "x-ratelimit-remaining-requests"),
                    last_updated=time.time(),
                )
                with self._lock:
                    self._stats = updated
        except urllib.error.HTTPError as e:
            # 4xx errors still return headers — extract them
            headers = e.headers
            if headers:
                updated = RateLimitStats(
                    tokens_limit=_int_header(headers, "x-ratelimit-limit-tokens"),
                    tokens_remaining=_int_header(headers, "x-ratelimit-remaining-tokens"),
                    requests_limit=_int_header(headers, "x-ratelimit-limit-requests"),
                    requests_remaining=_int_header(headers, "x-ratelimit-remaining-requests"),
                    last_updated=time.time(),
                )
                with self._lock:
                    self._stats = updated
        except Exception as e:
            logger.debug("API rate-limit poll failed: %s", e)


def _int_header(headers, name: str) -> int:
    val = headers.get(name)
    if val is None:
        return 0
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0
