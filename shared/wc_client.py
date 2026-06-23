"""Shared WooCommerce REST v3 client for Ifiale tooling.

Features
--------
- Automatic per_page=100 pagination (yields batches)
- Retry with exponential back-off on 429 / 5xx
- Configurable rate-limit delay (default 300 ms) – safe for Cloudways 1.92 GB
- Category-ID validation before any write operation
- Credentials loaded from .env (WC_CONSUMER_KEY / WC_CONSUMER_SECRET)
- All env loading centralised here; importers never touch .env directly

Usage
-----
    from shared.wc_client import WCClient, load_env

    ck, cs = load_env()
    client = WCClient(ck, cs)

    for batch in client.paginate("/wc/v3/products", {"status": "publish"}):
        for product in batch:
            ...

    client.validate_category_ids([651, 652])  # raises if any ID is invalid
    client.put("/wc/v3/products/123", {"name": "New name"}, dry_run=False)
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Generator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://ifialeinnovations.com/wp-json"
DEFAULT_RATE_LIMIT = 0.30   # seconds between API calls
DEFAULT_PER_PAGE = 100
MAX_RETRIES = 5
RETRY_STATUSES = {429, 500, 502, 503, 504}
BACKOFF_BASE = 1.5          # exponential back-off multiplier


# ---------------------------------------------------------------------------
# Credential loading
# ---------------------------------------------------------------------------

def load_env(env_path: Path | None = None) -> tuple[str, str]:
    """Load WC_CONSUMER_KEY and WC_CONSUMER_SECRET from .env or environment.

    Search order:
    1. OS environment variables
    2. ``env_path`` if provided
    3. Auto-discovered .env: walks up from this file until found

    Raises
    ------
    SystemExit
        When credentials are missing after all search locations are exhausted.
    """
    ck = os.environ.get("WC_CONSUMER_KEY", "")
    cs = os.environ.get("WC_CONSUMER_SECRET", "")
    if ck and cs:
        return ck, cs

    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path))
    # Walk up from this file's directory
    here = Path(__file__).resolve().parent
    for _ in range(5):
        candidates.append(here / ".env")
        here = here.parent

    for path in candidates:
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip().strip('"').strip("'")
                if key == "WC_CONSUMER_KEY" and val:
                    ck = val
                elif key == "WC_CONSUMER_SECRET" and val:
                    cs = val
            if ck and cs:
                return ck, cs

    raise SystemExit(
        "Missing WC_CONSUMER_KEY / WC_CONSUMER_SECRET. "
        "Set them in .env or as environment variables."
    )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class WCClient:
    """Minimal WooCommerce REST v3 client with pagination, retry, and rate-limiting.

    Parameters
    ----------
    consumer_key:
        WooCommerce REST API consumer key (``ck_…``).
    consumer_secret:
        WooCommerce REST API consumer secret (``cs_…``).
    base_url:
        Store root URL including ``/wp-json`` suffix.
    rate_limit:
        Minimum seconds to sleep between successive API calls.
    per_page:
        Default page size for paginated requests.
    """

    def __init__(
        self,
        consumer_key: str,
        consumer_secret: str,
        base_url: str = BASE_URL,
        rate_limit: float = DEFAULT_RATE_LIMIT,
        per_page: int = DEFAULT_PER_PAGE,
    ) -> None:
        token = base64.b64encode(f"{consumer_key}:{consumer_secret}".encode()).decode()
        self._headers: dict[str, str] = {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
            "User-Agent": "ifiale-wc-tools/2.0",
        }
        self._base = base_url.rstrip("/")
        self._rate_limit = rate_limit
        self._per_page = per_page
        self._last_call: float = 0.0
        self._valid_category_ids: set[int] | None = None

    # ------------------------------------------------------------------
    # Low-level request
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> tuple[Any, dict[str, str]]:
        """Execute a single HTTP request with rate-limiting and retry logic.

        Returns
        -------
        tuple[Any, dict[str, str]]
            Parsed JSON body and response headers dict.

        Raises
        ------
        RuntimeError
            On unrecoverable HTTP errors (4xx except 429).
        """
        url = f"{self._base}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None}
            )

        data = json.dumps(body).encode("utf-8") if body is not None else None

        for attempt in range(1, MAX_RETRIES + 1):
            # Enforce rate limit
            elapsed = time.monotonic() - self._last_call
            if elapsed < self._rate_limit:
                time.sleep(self._rate_limit - elapsed)

            req = urllib.request.Request(url, data=data, headers=self._headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    self._last_call = time.monotonic()
                    return json.loads(resp.read().decode()), dict(resp.headers)
            except urllib.error.HTTPError as exc:
                self._last_call = time.monotonic()
                if exc.code in RETRY_STATUSES and attempt < MAX_RETRIES:
                    wait = BACKOFF_BASE ** attempt
                    logger.warning(
                        "HTTP %s on %s %s – retry %d/%d in %.1fs",
                        exc.code, method, path, attempt, MAX_RETRIES, wait,
                    )
                    time.sleep(wait)
                    continue
                body_text = exc.read().decode(errors="replace")
                raise RuntimeError(
                    f"HTTP {exc.code} {method} {path}: {body_text[:400]}"
                ) from exc

        raise RuntimeError(f"Exhausted {MAX_RETRIES} retries for {method} {path}")

    # ------------------------------------------------------------------
    # Paginated GET
    # ------------------------------------------------------------------

    def paginate(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Generator[list[dict], None, None]:
        """Yield successive pages of results from a WooCommerce list endpoint.

        Parameters
        ----------
        path:
            API path, e.g. ``/wc/v3/products``.
        params:
            Extra query parameters merged with ``per_page`` and ``page``.

        Yields
        ------
        list[dict]
            One page of items at a time.

        Example
        -------
        ::

            for batch in client.paginate("/wc/v3/products", {"status": "publish"}):
                for product in batch:
                    process(product)
        """
        merged = dict(params or {})
        merged.setdefault("per_page", self._per_page)
        page = 1
        total_pages = 1

        while page <= total_pages:
            merged["page"] = page
            data, headers = self._request("GET", path, params=merged)
            total_pages = int(headers.get("X-WP-TotalPages", headers.get("x-wp-totalpages", 1)))
            total = int(headers.get("X-WP-Total", headers.get("x-wp-total", len(data))))
            logger.debug("GET %s page %d/%d (%d items)", path, page, total_pages, total)
            yield data
            page += 1

    def get_all(self, path: str, params: dict[str, Any] | None = None) -> list[dict]:
        """Fetch all pages and return as a flat list."""
        result: list[dict] = []
        for batch in self.paginate(path, params):
            result.extend(batch)
        return result

    # ------------------------------------------------------------------
    # Typed helpers
    # ------------------------------------------------------------------

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET a single resource and return the parsed body."""
        data, _ = self._request("GET", path, params=params)
        return data

    def put(
        self,
        path: str,
        body: dict[str, Any],
        dry_run: bool = True,
    ) -> Any:
        """PUT (update) a resource.

        Parameters
        ----------
        path:
            API path including the resource ID, e.g. ``/wc/v3/products/123``.
        body:
            Fields to update.
        dry_run:
            When *True* (default), log the call but do **not** send it.

        Returns
        -------
        Any
            Parsed response body, or *None* in dry-run mode.
        """
        if dry_run:
            logger.info("[DRY RUN] PUT %s %s", path, json.dumps(body)[:200])
            return None
        data, _ = self._request("PUT", path, body=body)
        return data

    def post(
        self,
        path: str,
        body: dict[str, Any],
        dry_run: bool = True,
    ) -> Any:
        """POST (create) a resource."""
        if dry_run:
            logger.info("[DRY RUN] POST %s %s", path, json.dumps(body)[:200])
            return None
        data, _ = self._request("POST", path, body=body)
        return data

    # ------------------------------------------------------------------
    # Category validation
    # ------------------------------------------------------------------

    def _fetch_valid_category_ids(self) -> set[int]:
        """Fetch and cache all valid WooCommerce product-category IDs."""
        if self._valid_category_ids is not None:
            return self._valid_category_ids
        ids: set[int] = set()
        for batch in self.paginate("/wc/v3/products/categories"):
            ids.update(c["id"] for c in batch if isinstance(c.get("id"), int))
        self._valid_category_ids = ids
        logger.info("Fetched %d valid category IDs", len(ids))
        return ids

    def validate_category_ids(self, ids: list[int]) -> None:
        """Assert every ID in *ids* exists in WooCommerce categories.

        Raises
        ------
        ValueError
            With a list of the invalid IDs.
        """
        valid = self._fetch_valid_category_ids()
        bad = [i for i in ids if i not in valid]
        if bad:
            raise ValueError(
                f"Invalid WooCommerce category IDs (not found in store): {bad}. "
                "Run audit_wc_catalog_health.py to see the current category tree."
            )

    # ------------------------------------------------------------------
    # Convenience: product by SKU
    # ------------------------------------------------------------------

    def get_by_sku(self, sku: str) -> list[dict]:
        """Return all products with the given SKU (normally 0 or 1)."""
        data, _ = self._request("GET", "/wc/v3/products", params={"sku": sku, "per_page": 10})
        return data if isinstance(data, list) else []
