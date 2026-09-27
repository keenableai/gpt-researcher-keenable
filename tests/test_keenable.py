"""Offline tests for the Keenable GPT Researcher plugin.

``requests.post`` is replaced with a recorder, so nothing touches the network.
The live test runs only with ``KEENABLE_LIVE_TESTS=1`` and uses the keyless
endpoint.
"""

import os
from importlib.metadata import entry_points

import pytest
import requests

import gpt_researcher_keenable as plugin
from gpt_researcher_keenable import KeenableSearch


class _Resp:
    def __init__(self, payload=None, status=200, exc=None):
        self._payload = payload
        self.status_code = status
        self._exc = exc

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def json(self):
        if self._exc:
            raise self._exc
        return self._payload


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("KEENABLE_API_KEY", "KEENABLE_API_URL"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def post(monkeypatch):
    calls = []
    state = {"resp": _Resp({"results": []})}

    def fake_post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        if isinstance(state["resp"], Exception):
            raise state["resp"]
        return state["resp"]

    monkeypatch.setattr(plugin.requests, "post", fake_post)
    fake_post.calls = calls
    fake_post.state = state
    return fake_post


def _item(i, **extra):
    return {"title": f"T{i}", "url": f"https://example.com/{i}", "description": "", **extra}


def test_keyless_by_default(post):
    KeenableSearch("rust async").search()
    call = post.calls[0]
    assert call["url"] == "https://api.keenable.ai/v1/search/public"
    assert "X-API-Key" not in call["headers"]
    assert call["headers"]["X-Keenable-Title"] == "GPT-Researcher"
    assert call["allow_redirects"] is False


def test_key_selects_authenticated_endpoint(post, monkeypatch):
    monkeypatch.setenv("KEENABLE_API_KEY", "  keen_test  ")
    KeenableSearch("q").search()
    call = post.calls[0]
    assert call["url"] == "https://api.keenable.ai/v1/search"
    assert call["headers"]["X-API-Key"] == "keen_test"
    assert "keen_test" not in call["url"]
    assert "keen_test" not in str(call["json"])


def test_payload_carries_query_limit_and_first_domain(post):
    KeenableSearch("q", query_domains=["docs.python.org", "peps.python.org"]).search(5)
    assert post.calls[0]["json"] == {"query": "q", "max_results": 5, "site": "docs.python.org"}


def test_payload_has_no_site_without_domains(post):
    KeenableSearch("q", query_domains=[]).search()
    assert "site" not in post.calls[0]["json"]


@pytest.mark.parametrize("asked, sent", [(0, 1), (-3, 1), (7, 7), (50, 50), (200, 50)])
def test_limit_is_clamped_to_api_range(post, asked, sent):
    KeenableSearch("q").search(asked)
    assert post.calls[0]["json"]["max_results"] == sent


def test_maps_snippet_into_capped_single_line_body(post):
    long = "word\n\n  " * 400
    post.state["resp"] = _Resp({"results": [_item(1, snippet=long)]})
    [result] = KeenableSearch("q").search()
    assert result["href"] == "https://example.com/1"
    assert result["title"] == "T1"
    assert "\n" not in result["body"]
    assert len(result["body"]) == plugin.MAX_BODY_CHARS


def test_falls_back_to_description(post):
    post.state["resp"] = _Resp({"results": [_item(1, description="short text")]})
    assert KeenableSearch("q").search()[0]["body"] == "short text"


def test_drops_results_without_url_before_limiting(post):
    items = [{"title": "no url"}, _item(1), "junk", _item(2), _item(3)]
    post.state["resp"] = _Resp({"results": items})
    results = KeenableSearch("q").search(2)
    assert [r["href"] for r in results] == ["https://example.com/1", "https://example.com/2"]


@pytest.mark.parametrize(
    "resp",
    [
        _Resp(status=429),
        _Resp(status=500),
        _Resp(exc=ValueError("not json")),
        _Resp(payload=["not", "a", "dict"]),
        _Resp(payload={"results": None}),
        requests.ConnectionError("down"),
        requests.Timeout("slow"),
    ],
)
def test_failures_return_empty_list(post, resp):
    post.state["resp"] = resp
    assert KeenableSearch("q").search() == []


def test_failure_log_does_not_leak_key(post, monkeypatch, caplog):
    monkeypatch.setenv("KEENABLE_API_KEY", "keen_secret")
    post.state["resp"] = requests.ConnectionError("https://x?key=keen_secret")
    KeenableSearch("q").search()
    assert "keen_secret" not in caplog.text


@pytest.mark.parametrize(
    "url",
    [
        "http://api.keenable.ai",
        "ftp://api.keenable.ai",
        "https://",
        "https://api.keenable.ai?x=1",
        "https://api.keenable.ai#frag",
    ],
)
def test_rejects_unsafe_base_url_without_raising(post, monkeypatch, url):
    monkeypatch.setenv("KEENABLE_API_URL", url)
    assert KeenableSearch("q").search() == []
    assert post.calls == []


@pytest.mark.parametrize(
    "url", ["http://localhost:8080", "http://127.0.0.1", "https://proxy.test/"]
)
def test_accepts_https_and_loopback_http(post, monkeypatch, url):
    monkeypatch.setenv("KEENABLE_API_URL", url)
    KeenableSearch("q").search()
    assert post.calls[0]["url"] == url.rstrip("/") + "/v1/search/public"


def test_scraping_is_declared():
    assert KeenableSearch.requires_scraping is True


def test_entry_point_is_registered():
    [ep] = entry_points(group="gpt_researcher.retrievers", name="keenable")
    assert ep.load() is KeenableSearch


@pytest.mark.skipif(os.environ.get("KEENABLE_LIVE_TESTS") != "1", reason="live test")
def test_live_keyless(monkeypatch):
    monkeypatch.delenv("KEENABLE_API_KEY", raising=False)
    results = KeenableSearch("python asyncio tutorial").search(5)
    assert 0 < len(results) <= 5
    assert all(r["href"].startswith("http") and r["body"] for r in results)
