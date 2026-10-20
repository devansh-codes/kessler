"""Polite HTTP client.

CelesTrak firewalls IPs that make ~50 failed requests within 2 hours, and GP data only
changes every ~2 hours. This client therefore:

* caches every successful response on disk and never re-requests within the TTL,
* refuses hosts that are known to redirect (``celestrak.com``),
* stops the whole run on the first non-200 response (no retries, ever),
* keeps a persistent error ledger and refuses to make requests once a small budget is spent,
* records every request in ``self.log`` so ``ingest_log`` can be written.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

from kessler import __version__

USER_AGENT = f"kessler/{__version__} (+https://github.com/devansh-codes/kessler)"
DEFAULT_TTL_S = 2 * 3600
ALLOWED_HOSTS = {"celestrak.org", "planet4589.org", "services.swpc.noaa.gov"}
FORBIDDEN_HOSTS = {"celestrak.com", "www.celestrak.com", "www.celestrak.org"}
ERROR_WINDOW_S = 2 * 3600
ERROR_BUDGET = 5  # far below CelesTrak's ~50/2h firewall threshold


class HttpStop(RuntimeError):
    """Raised on a non-200 response or when the client refuses to make a request."""

    def __init__(self, url: str, status: int | None, message: str):
        super().__init__(f"{message} [{status}] {url}")
        self.url = url
        self.status = status


@dataclass
class RequestRecord:
    url: str
    status: int | None
    bytes: int
    from_cache: bool
    duration_ms: int
    started_at: str
    error: str | None = None


@dataclass
class Fetched:
    url: str
    text: str
    status: int
    from_cache: bool
    fetched_at: datetime

    @property
    def content(self) -> bytes:
        return self.text.encode()


@dataclass
class PoliteClient:
    cache_dir: Path
    ttl_s: int = DEFAULT_TTL_S
    timeout_s: float = 60.0
    transport: httpx.BaseTransport | None = None
    now: callable = field(default=lambda: time.time())  # injectable clock for tests
    log: list[RequestRecord] = field(default_factory=list)
    stopped: bool = False

    def __post_init__(self) -> None:
        self.cache_dir = Path(self.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"},
            timeout=self.timeout_s,
            follow_redirects=False,
            transport=self.transport,
        )

    # ----------------------------------------------------------------- cache
    def _key(self, url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()[:32]

    def _paths(self, url: str) -> tuple[Path, Path]:
        k = self._key(url)
        return self.cache_dir / f"{k}.body", self.cache_dir / f"{k}.json"

    def cached(self, url: str, ttl_s: int | None = None) -> Fetched | None:
        body, meta = self._paths(url)
        if not (body.exists() and meta.exists()):
            return None
        m = json.loads(meta.read_text())
        age = self.now() - m["fetched_at_unix"]
        if age > (self.ttl_s if ttl_s is None else ttl_s):
            return None
        return Fetched(
            url=url,
            text=body.read_text(),
            status=m["status"],
            from_cache=True,
            fetched_at=datetime.fromtimestamp(m["fetched_at_unix"], UTC),
        )

    def _store(self, url: str, text: str, status: int) -> None:
        body, meta = self._paths(url)
        body.write_text(text)
        meta.write_text(json.dumps({"url": url, "status": status, "fetched_at_unix": self.now()}))

    # ---------------------------------------------------------- error ledger
    @property
    def _ledger(self) -> Path:
        return self.cache_dir / "_errors.json"

    def _recent_errors(self) -> list[dict]:
        if not self._ledger.exists():
            return []
        cutoff = self.now() - ERROR_WINDOW_S
        return [e for e in json.loads(self._ledger.read_text()) if e["t"] >= cutoff]

    def _record_error(self, url: str, status: int | None, msg: str) -> None:
        errs = self._recent_errors() + [{"t": self.now(), "url": url, "status": status, "msg": msg}]
        self._ledger.write_text(json.dumps(errs, indent=1))

    # ----------------------------------------------------------------- fetch
    def get(self, url: str, ttl_s: int | None = None) -> Fetched:
        host = urlparse(url).hostname or ""
        if urlparse(url).scheme != "https":
            raise HttpStop(url, None, "only https is allowed")
        if host in FORBIDDEN_HOSTS:
            raise HttpStop(url, None, f"host {host} redirects; use celestrak.org")
        if host not in ALLOWED_HOSTS:
            raise HttpStop(url, None, f"host {host} is not on the allowlist")

        hit = self.cached(url, ttl_s)
        if hit is not None:
            self.log.append(RequestRecord(url, hit.status, len(hit.text), True, 0, _iso(self.now())))
            return hit

        if self.stopped:
            raise HttpStop(url, None, "client stopped after an earlier error; refusing further requests")
        if len(self._recent_errors()) >= ERROR_BUDGET:
            self.stopped = True
            raise HttpStop(url, None, f"error budget exhausted ({ERROR_BUDGET} errors in 2h)")

        started = self.now()
        t0 = time.perf_counter()
        try:
            r = self._client.get(url)
        except httpx.HTTPError as e:
            ms = int((time.perf_counter() - t0) * 1000)
            self.stopped = True
            self._record_error(url, None, repr(e))
            self.log.append(RequestRecord(url, None, 0, False, ms, _iso(started), repr(e)))
            raise HttpStop(url, None, f"transport error: {e!r}") from e
        ms = int((time.perf_counter() - t0) * 1000)

        if r.status_code != 200:
            self.stopped = True
            msg = f"HTTP {r.status_code}"
            self._record_error(url, r.status_code, msg)
            self.log.append(RequestRecord(url, r.status_code, len(r.content), False, ms, _iso(started), msg))
            raise HttpStop(url, r.status_code, "non-200 response; stopping (no retry)")

        text = r.text
        self._store(url, text, r.status_code)
        self.log.append(RequestRecord(url, 200, len(r.content), False, ms, _iso(started)))
        return Fetched(url, text, 200, False, datetime.fromtimestamp(started, UTC))

    def network_calls(self) -> int:
        return sum(1 for rec in self.log if not rec.from_cache)

    def records(self) -> list[dict]:
        return [asdict(r) for r in self.log]

    def close(self) -> None:
        self._client.close()


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).isoformat(timespec="seconds")
