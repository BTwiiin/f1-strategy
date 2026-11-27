"""OpenF1 client with a raw response cache and request manifest.

Responses are stored byte-for-byte; the manifest records URL, parameters, retrieval time,
HTTP status, row count and SHA-256 of each cached response. A request already in the
manifest is never refetched, so interrupted ingestion resumes where it stopped.
"""

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MANIFEST = "manifest.jsonl"

# OpenF1 answers a query without matching rows with HTTP 404; it is cached as an empty result.
EMPTY_STATUS = 404
RETRY_STATUS = {429, 500, 502, 503, 504}

# (url, timeout) -> (status, body)
Fetch = Callable[[str, float], tuple[int, bytes]]


class FetchError(RuntimeError):
    pass


def urllib_fetch(url: str, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


@dataclass
class RateLimiter:
    """Sliding-window limits on requests per second and per minute."""

    max_per_second: int
    max_per_minute: int
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    _sent: deque[float] = field(default_factory=deque)

    def wait(self) -> None:
        while True:
            now = self.clock()
            while self._sent and now - self._sent[0] >= 60:
                self._sent.popleft()
            in_second = sum(1 for t in self._sent if now - t < 1)
            if len(self._sent) < self.max_per_minute and in_second < self.max_per_second:
                self._sent.append(now)
                return
            if len(self._sent) >= self.max_per_minute:
                delay = 60 - (now - self._sent[0])
            else:
                delay = 1 - (now - self._sent[-in_second])
            self.sleep(max(delay, 0.01))


def query_key(endpoint: str, params: dict[str, Any]) -> str:
    query = urllib.parse.urlencode(sorted(params.items()))
    return hashlib.sha256(f"{endpoint}?{query}".encode()).hexdigest()[:20]


class Client:
    """Cached OpenF1 client for one role's raw directory (``<raw_dir>/<role>``)."""

    def __init__(
        self,
        root: Path,
        base_url: str,
        limiter: RateLimiter,
        *,
        max_attempts: int = 5,
        backoff_base_s: float = 2.0,
        timeout_s: float = 60,
        fetch: Fetch = urllib_fetch,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.root = root
        self.base_url = base_url.rstrip("/")
        self.limiter = limiter
        self.max_attempts = max_attempts
        self.backoff_base_s = backoff_base_s
        self.timeout_s = timeout_s
        self.fetch = fetch
        self.sleep = sleep
        self.manifest = read_manifest(root)
        self.fetched = 0

    def ensure(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        """Cache the response if not cached yet; return its manifest entry."""
        key = f"{endpoint}/{query_key(endpoint, params)}.json"
        entry = self.manifest.get(key)
        return entry if entry is not None else self._download(endpoint, params, key)

    def get(self, endpoint: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Rows for ``endpoint`` filtered by ``params``, from the cache when available."""
        entry = self.ensure(endpoint, params)
        if entry["status"] == EMPTY_STATUS:
            return []
        return json.loads((self.root / entry["key"]).read_bytes())

    def _download(self, endpoint: str, params: dict[str, Any], key: str) -> dict[str, Any]:
        url = f"{self.base_url}/{endpoint}?{urllib.parse.urlencode(sorted(params.items()))}"
        for attempt in range(self.max_attempts):
            self.limiter.wait()
            try:
                status, body = self.fetch(url, self.timeout_s)
            except (urllib.error.URLError, TimeoutError) as e:
                status, body = None, str(e).encode()
            if status == 200 or status == EMPTY_STATUS:
                break
            if status is not None and status not in RETRY_STATUS:
                raise FetchError(f"{url}: HTTP {status}: {body[:200]!r}")
            self.sleep(self.backoff_base_s * 2**attempt)
        else:
            raise FetchError(f"{url}: failed after {self.max_attempts} attempts")

        rows = json.loads(body) if status == 200 else []
        if not isinstance(rows, list):
            raise FetchError(f"{url}: expected a JSON array")
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(body)
        os.replace(tmp, path)
        entry = {
            "key": key,
            "endpoint": endpoint,
            "params": dict(sorted(params.items())),
            "url": url,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "status": status,
            "rows": len(rows),
            "sha256": hashlib.sha256(body).hexdigest(),
        }
        # Appended only after the response file is in place: a crash in between leaves an
        # unlisted file that is refetched and overwritten on the next run.
        with (self.root / MANIFEST).open("a") as f:
            f.write(json.dumps(entry) + "\n")
        self.manifest[key] = entry
        self.fetched += 1
        return entry


def read_manifest(root: Path) -> dict[str, dict[str, Any]]:
    """Latest manifest entry per cache key."""
    path = root / MANIFEST
    if not path.exists():
        return {}
    entries = {}
    for line in path.read_text().splitlines():
        if line.strip():
            e = json.loads(line)
            entries[e["key"]] = e
    return entries
