"""
Shared utilities for SerpApi flight and hotel search scripts.

Provides: API key loading, search with retry, timestamp injection,
image stripping, and atomic cache read/write.
"""
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def get_api_key():
    """Read SERPAPI_API_KEY from environment. Returns None if unset."""
    return os.environ.get("SERPAPI_API_KEY")


def serpapi_search(params, retries=3):
    """Call SerpApi with retry + exponential backoff.

    Args:
        params: dict of SerpApi query parameters (must include 'engine').
        retries: max attempts before raising.

    Returns:
        Parsed JSON response dict.
    """
    from serpapi import Client

    api_key = get_api_key()
    if not api_key:
        raise RuntimeError("SERPAPI_API_KEY not set in environment")

    client = Client(api_key=api_key)

    last_error = None
    for attempt in range(retries):
        try:
            result = client.search(params)
            return dict(result)
        except Exception as e:
            last_error = e
            if attempt < retries - 1:
                wait = 2 ** attempt
                logger.warning("SerpApi attempt %d failed: %s — retrying in %ds", attempt + 1, e, wait)
                time.sleep(wait)

    raise RuntimeError(f"SerpApi failed after {retries} attempts: {last_error}")


def add_fetched_at(items):
    """Add fetched_at (UTC ISO) timestamp to each dict in the list."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for item in items:
        item["fetched_at"] = now
    return items


def strip_images(properties):
    """Remove 'images' key from each hotel property dict."""
    for prop in properties:
        prop.pop("images", None)
    return properties


def write_cache(cache_path, data):
    """Atomically write JSON data to cache_path (UTF-8, makedirs)."""
    path = Path(cache_path)
    os.makedirs(path.parent, exist_ok=True)

    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp_path.replace(path)


def read_cache(cache_path):
    """Read existing cache JSON. Returns None if missing or corrupted."""
    path = Path(cache_path)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Cache corrupted or unreadable at %s: %s", cache_path, e)
        return None
