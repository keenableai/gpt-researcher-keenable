"""Keenable web search as a GPT Researcher retriever plugin.

Install next to GPT Researcher (0.16.1 or later) and select it by name::

    pip install gpt-researcher-keenable
    export RETRIEVER=keenable

No API key is needed: without ``KEENABLE_API_KEY`` the public endpoint is
used. Setting a key (https://keenable.ai/console) lifts the rate limits.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlsplit

import requests

__all__ = ["KeenableSearch"]
__version__ = "0.1.0"

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.keenable.ai"
# `body` is a preview: GPT Researcher scrapes each `href` for the real page, so
# keep it snippet-sized like the built-in web retrievers. Keenable's `snippet`
# is raw page text of a few thousand characters.
MAX_BODY_CHARS = 500
# The API accepts 1-50 results per call.
MIN_RESULTS, MAX_RESULTS = 1, 50
TIMEOUT_SECONDS = 30
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _base_url() -> str:
    base = (os.environ.get("KEENABLE_API_URL") or DEFAULT_BASE_URL).rstrip("/")
    parsed = urlsplit(base)
    if parsed.hostname and not parsed.query and not parsed.fragment:
        if parsed.scheme == "https":
            return base
        # Plain http only against a loopback host (local development).
        if parsed.scheme == "http" and parsed.hostname in _LOOPBACK_HOSTS:
            return base
    raise ValueError(f"KEENABLE_API_URL must be an https:// URL with a host, got {base!r}")


def _body(item: dict[str, Any]) -> str:
    # `description` is usually empty; `snippet` carries the page text.
    text = " ".join(str(item.get("snippet") or item.get("description") or "").split())
    return text[:MAX_BODY_CHARS]


class KeenableSearch:
    """GPT Researcher retriever backed by the Keenable search API.

    Follows the ``gpt_researcher.retrievers`` plugin contract: constructed with
    the sub-query and an optional domain filter, ``search()`` returns a list of
    ``{"title", "href", "body"}`` dicts and ``[]`` on any failure.
    """

    #: Results are links with a short preview; GPT Researcher scrapes the pages.
    requires_scraping = True

    def __init__(self, query: str, query_domains: list[str] | None = None, **kwargs: Any):
        self.query = query
        self.query_domains = list(query_domains or [])
        self.api_key = (os.environ.get("KEENABLE_API_KEY") or "").strip()
        # A bad KEENABLE_API_URL is reported, not raised: the contract is that
        # a failing provider yields no results instead of aborting the run.
        try:
            self.base_url: str | None = _base_url()
        except ValueError as exc:
            logger.error("%s", exc)
            self.base_url = None

    def search(self, max_results: int = 7) -> list[dict[str, Any]]:
        if self.base_url is None:
            return []
        limit = max(MIN_RESULTS, min(MAX_RESULTS, int(7 if max_results is None else max_results)))
        headers = {
            "Content-Type": "application/json",
            "User-Agent": f"gpt-researcher-keenable/{__version__}",
            # Required on keyless calls (400 without it); also attributes traffic.
            "X-Keenable-Title": "GPT-Researcher",
        }
        if self.api_key:
            path = "/v1/search"
            headers["X-API-Key"] = self.api_key
        else:
            path = "/v1/search/public"

        payload: dict[str, Any] = {"query": self.query, "max_results": limit}
        # The API filters by a single site, so the first domain is used.
        if self.query_domains:
            payload["site"] = self.query_domains[0]

        try:
            response = requests.post(
                f"{self.base_url}{path}",
                json=payload,
                headers=headers,
                timeout=TIMEOUT_SECONDS,
                allow_redirects=False,
            )
            response.raise_for_status()
            items = response.json().get("results") or []
        except (requests.RequestException, ValueError, AttributeError) as exc:
            # Never let one provider abort a research run.
            logger.warning("Keenable search failed: %s", type(exc).__name__)
            return []

        results = [
            {"title": item.get("title") or "", "href": item["url"], "body": _body(item)}
            for item in items
            if isinstance(item, dict) and item.get("url")
        ]
        return results[:limit]
