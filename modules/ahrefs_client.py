"""Ahrefs API v3 client with disk cache, rate limiting, retry and logging.

Endpoint paths and field names follow the public Ahrefs v3 reference
(https://docs.ahrefs.com/docs/api/reference/). Some parameter names differ
between endpoints (e.g. `volume_from` vs `min_volume`); the analyzer modules
build their own `where` filter strings, so this client stays generic.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

BASE_URL = "https://api.ahrefs.com/v3"
DEFAULT_TIMEOUT = 60


class AhrefsError(Exception):
    pass


class AhrefsRateLimitError(AhrefsError):
    pass


class AhrefsServerError(AhrefsError):
    pass


@dataclass
class AhrefsConfig:
    token: str
    country: str = "fr"
    language: str = "fr"
    cache_dir: Path = Path("cache")
    log_path: Path = Path("logs/ahrefs.log")
    cache_ttl_seconds: int = 7 * 24 * 3600
    rate_limit_per_min: int = 60

    @classmethod
    def from_env(cls) -> "AhrefsConfig":
        token = os.environ.get("AHREFS_API_TOKEN", "").strip()
        if not token:
            raise AhrefsError(
                "AHREFS_API_TOKEN is not set. Copy .env.example to .env and fill it in."
            )
        return cls(
            token=token,
            country=os.environ.get("COUNTRY", "fr"),
            language=os.environ.get("LANGUAGE", "fr"),
            cache_ttl_seconds=int(os.environ.get("CACHE_TTL_HOURS", "168")) * 3600,
            rate_limit_per_min=int(os.environ.get("RATE_LIMIT_PER_MIN", "60")),
        )


class _RateLimiter:
    def __init__(self, calls_per_min: int) -> None:
        self.interval = 60.0 / max(calls_per_min, 1)
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            sleep_for = self._next_allowed - now
            if sleep_for > 0:
                time.sleep(sleep_for)
                now = time.monotonic()
            self._next_allowed = now + self.interval


def _setup_logger(log_path: Path, level: str = "INFO") -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("ahrefs")
    if logger.handlers:
        return logger
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    )
    logger.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("[ahrefs] %(message)s"))
    logger.addHandler(sh)
    return logger


class AhrefsClient:
    def __init__(self, config: AhrefsConfig | None = None) -> None:
        self.config = config or AhrefsConfig.from_env()
        self.config.cache_dir.mkdir(parents=True, exist_ok=True)
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self.config.token}",
                "Accept": "application/json",
                "User-Agent": "esprit-riche-seo/0.1",
            }
        )
        self._limiter = _RateLimiter(self.config.rate_limit_per_min)
        self._log = _setup_logger(
            self.config.log_path, os.environ.get("LOG_LEVEL", "INFO")
        )

    def _cache_key(self, path: str, params: dict[str, Any]) -> Path:
        canonical = json.dumps(params, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha1(f"{path}?{canonical}".encode("utf-8")).hexdigest()
        safe = path.strip("/").replace("/", "_")
        return self.config.cache_dir / f"{safe}_{digest}.json"

    def _load_cache(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        age = time.time() - path.stat().st_mtime
        if age > self.config.cache_ttl_seconds:
            self._log.debug("cache expired: %s (age=%.0fs)", path.name, age)
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self._log.warning("cache corrupt, ignoring: %s", path.name)
            return None

    def _store_cache(self, path: Path, payload: dict[str, Any]) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    @retry(
        retry=retry_if_exception_type((AhrefsRateLimitError, AhrefsServerError)),
        wait=wait_exponential(multiplier=2, min=2, max=60),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _request(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        self._limiter.wait()
        url = f"{BASE_URL}{path}"
        self._log.info("GET %s?%s", path, urlencode(params, doseq=True))
        try:
            resp = self._session.get(url, params=params, timeout=DEFAULT_TIMEOUT)
        except requests.RequestException as exc:
            self._log.error("network error: %s", exc)
            raise AhrefsServerError(str(exc)) from exc

        if resp.status_code == 429:
            self._log.warning("rate limited (429), backing off")
            raise AhrefsRateLimitError("rate limited")
        if 500 <= resp.status_code < 600:
            self._log.warning("server error %d: %s", resp.status_code, resp.text[:200])
            raise AhrefsServerError(f"{resp.status_code}")
        if resp.status_code >= 400:
            self._log.error("client error %d: %s", resp.status_code, resp.text[:500])
            raise AhrefsError(f"{resp.status_code}: {resp.text[:500]}")

        try:
            return resp.json()
        except ValueError as exc:
            raise AhrefsError(f"invalid JSON response: {exc}") from exc

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        cache_path = self._cache_key(path, params)
        if use_cache:
            cached = self._load_cache(cache_path)
            if cached is not None:
                self._log.debug("cache hit: %s", cache_path.name)
                return cached
        payload = self._request(path, params)
        self._store_cache(cache_path, payload)
        return payload

    def organic_keywords(
        self,
        target: str,
        *,
        limit: int = 1000,
        where: str | None = None,
        order_by: str = "traffic:desc",
        select: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch organic keywords for a domain or URL."""
        default_select = (
            "keyword,volume,keyword_difficulty,position,url,traffic,"
            "cpc,intents,parent_topic,sf"
        )
        params = {
            "target": target,
            "country": self.config.country,
            "mode": "subdomains",
            "limit": limit,
            "select": select or default_select,
            "order_by": order_by,
            "output": "json",
        }
        if where:
            params["where"] = where
        data = self.get("/site-explorer/organic-keywords", params)
        return data.get("keywords", data.get("rows", []))

    def competitors(self, target: str, *, limit: int = 20) -> list[dict[str, Any]]:
        params = {
            "target": target,
            "country": self.config.country,
            "limit": limit,
            "output": "json",
        }
        data = self.get("/site-explorer/competitors-overview", params)
        return data.get("competitors", data.get("rows", []))

    def keywords_overview(self, keywords: list[str]) -> list[dict[str, Any]]:
        params = {
            "country": self.config.country,
            "keywords": ",".join(keywords),
            "output": "json",
        }
        data = self.get("/keywords-explorer/overview", params)
        return data.get("keywords", data.get("rows", []))

    def matching_terms(
        self,
        seed: str,
        *,
        limit: int = 200,
        match_mode: str = "terms",
        where: str | None = None,
    ) -> list[dict[str, Any]]:
        params = {
            "country": self.config.country,
            "keywords": seed,
            "match_mode": match_mode,
            "limit": limit,
            "select": "keyword,volume,keyword_difficulty,cpc,intents,parent_topic",
            "order_by": "volume:desc",
            "output": "json",
        }
        if where:
            params["where"] = where
        data = self.get("/keywords-explorer/matching-terms", params)
        return data.get("keywords", data.get("rows", []))

    def volume_history(self, keyword: str) -> list[dict[str, Any]]:
        params = {
            "country": self.config.country,
            "keyword": keyword,
            "output": "json",
        }
        data = self.get("/keywords-explorer/volume-history", params)
        return data.get("history", data.get("rows", []))
