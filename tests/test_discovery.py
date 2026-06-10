import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from pipeline.discovery import discover

NOW = datetime.now(tz=UTC)
RECENT = NOW - timedelta(hours=10)
OLD = NOW - timedelta(hours=72)

RSS_SOURCE = {"name": "Test RSS", "url": "http://example.com/feed", "type": "rss", "active": True}
HN_SOURCE = {
    "name": "Hacker News",
    "url": "https://hn.algolia.com/api/v1/search_by_date",
    "type": "hn",
    "active": True,
}
INACTIVE = {"name": "Inactive", "url": "http://example.com/old", "type": "rss", "active": False}


def write_sources(tmp_path: Path, sources: list[dict]) -> Path:
    p = tmp_path / "sources.json"
    p.write_text(json.dumps(sources))
    return p


def rss_entry(title: str, url: str, published: datetime, summary: str = "") -> dict:
    return {
        "link": url,
        "title": title,
        "summary": summary,
        "description": "",
        "published_parsed": time.gmtime(int(published.timestamp())),
        "published": published.isoformat(),
    }


def fake_feed(entries: list) -> MagicMock:
    f = MagicMock()
    f.entries = entries
    return f


def mock_rss_client(url_to_raise: str | None = None):
    """httpx mock for RSS: returns empty bytes content; optionally raises for one URL."""
    ok_resp = MagicMock()
    ok_resp.raise_for_status = MagicMock()
    ok_resp.content = b""

    fail_resp = MagicMock()
    fail_resp.raise_for_status.side_effect = Exception("network error")

    async def fake_get(url, **kwargs):
        return fail_resp if str(url) == url_to_raise else ok_resp

    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get = fake_get
    return client


def mock_hn_client(hits: list[dict]) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"hits": hits}
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get = AsyncMock(return_value=resp)
    return client


def hn_hit(title: str, url: str, published: datetime, story_text: str = "") -> dict:
    return {
        "title": title,
        "url": url,
        "created_at": published.isoformat(),
        "story_text": story_text,
    }


# --- RSS parsing ---


async def test_rss_parses_fields(tmp_path):
    p = write_sources(tmp_path, [RSS_SOURCE])
    entry = rss_entry("My Article", "http://ex.com/a", RECENT, "A summary")
    with patch("pipeline.discovery.httpx.AsyncClient", return_value=mock_rss_client()):
        with patch("pipeline.discovery.feedparser.parse", return_value=fake_feed([entry])):
            articles = await discover(p)
    assert len(articles) == 1
    a = articles[0]
    assert a["title"] == "My Article"
    assert a["url"] == "http://ex.com/a"
    assert a["source"] == "Test RSS"
    assert a["snippet"] == "A summary"
    assert isinstance(a["published_at"], datetime)
    assert a["published_at"].tzinfo is not None


async def test_rss_skips_entry_without_url(tmp_path):
    p = write_sources(tmp_path, [RSS_SOURCE])
    with patch("pipeline.discovery.httpx.AsyncClient", return_value=mock_rss_client()):
        with patch(
            "pipeline.discovery.feedparser.parse",
            return_value=fake_feed([rss_entry("No URL", "", RECENT)]),
        ):
            articles = await discover(p)
    assert articles == []


async def test_rss_skips_entry_without_date(tmp_path):
    p = write_sources(tmp_path, [RSS_SOURCE])
    entry = {
        "link": "http://ex.com/nodatearticle",
        "title": "No Date",
        "summary": "",
        "description": "",
    }
    with patch("pipeline.discovery.httpx.AsyncClient", return_value=mock_rss_client()):
        with patch("pipeline.discovery.feedparser.parse", return_value=fake_feed([entry])):
            articles = await discover(p)
    assert articles == []


# --- HN parsing ---


async def test_hn_parses_hits(tmp_path):
    p = write_sources(tmp_path, [HN_SOURCE])
    hit = hn_hit("HN Story", "http://hn.example.com/s", RECENT, "some context")
    with patch("pipeline.discovery.httpx.AsyncClient", return_value=mock_hn_client([hit])):
        articles = await discover(p)
    assert len(articles) == 1
    a = articles[0]
    assert a["title"] == "HN Story"
    assert a["url"] == "http://hn.example.com/s"
    assert a["source"] == "Hacker News"
    assert a["snippet"] == "some context"


async def test_hn_skips_hits_without_url(tmp_path):
    p = write_sources(tmp_path, [HN_SOURCE])
    hit = {"title": "Ask HN: stuff", "url": "", "created_at": RECENT.isoformat()}
    with patch("pipeline.discovery.httpx.AsyncClient", return_value=mock_hn_client([hit])):
        articles = await discover(p)
    assert articles == []


async def test_hn_query_does_not_contain_literal_plus():
    from pipeline.discovery import _HN_BASE_PARAMS

    assert _HN_BASE_PARAMS["query"] == "data engineering"
    assert "+" not in _HN_BASE_PARAMS["query"]


async def test_hn_sends_numeric_filter_for_recent_stories(tmp_path):
    p = write_sources(tmp_path, [HN_SOURCE])
    captured_params: dict = {}

    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"hits": []}

    async def fake_get(url, params=None, **kwargs):
        if params:
            captured_params.update(params)
        return resp

    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get = fake_get

    with patch("pipeline.discovery.httpx.AsyncClient", return_value=client):
        await discover(p)

    assert "numericFilters" in captured_params
    filt = captured_params["numericFilters"]
    assert filt.startswith("created_at_i>")
    cutoff_ts = int(filt.split(">")[1])
    expected_ts = int((NOW - timedelta(hours=48)).timestamp())
    assert abs(cutoff_ts - expected_ts) < 5


async def test_rss_client_follows_redirects(tmp_path):
    p = write_sources(tmp_path, [RSS_SOURCE])
    captured_kwargs: dict = {}

    def client_factory(**kwargs):
        captured_kwargs.update(kwargs)
        return mock_rss_client()

    with patch("pipeline.discovery.httpx.AsyncClient", side_effect=client_factory):
        with patch("pipeline.discovery.feedparser.parse", return_value=fake_feed([])):
            await discover(p)

    assert captured_kwargs.get("follow_redirects") is True


# --- 48h filter ---


async def test_filters_articles_older_than_48h(tmp_path):
    p = write_sources(tmp_path, [RSS_SOURCE])
    entries = [
        rss_entry("Recent", "http://ex.com/new", RECENT),
        rss_entry("Old", "http://ex.com/old", OLD),
    ]
    with patch("pipeline.discovery.httpx.AsyncClient", return_value=mock_rss_client()):
        with patch("pipeline.discovery.feedparser.parse", return_value=fake_feed(entries)):
            articles = await discover(p)
    assert len(articles) == 1
    assert articles[0]["title"] == "Recent"


async def test_article_exactly_at_cutoff_boundary_is_included(tmp_path):
    p = write_sources(tmp_path, [RSS_SOURCE])
    just_inside = NOW - timedelta(hours=47, minutes=59)
    with patch("pipeline.discovery.httpx.AsyncClient", return_value=mock_rss_client()):
        with patch(
            "pipeline.discovery.feedparser.parse",
            return_value=fake_feed([rss_entry("Borderline", "http://ex.com/border", just_inside)]),
        ):
            articles = await discover(p)
    assert len(articles) == 1


# --- URL dedup ---


async def test_deduplicates_same_url_across_sources(tmp_path):
    src_a = {"name": "A", "url": "http://a.com/feed", "type": "rss", "active": True}
    src_b = {"name": "B", "url": "http://b.com/feed", "type": "rss", "active": True}
    p = write_sources(tmp_path, [src_a, src_b])
    shared_url = "http://shared.com/article"
    feeds = iter(
        [
            fake_feed([rss_entry("Article", shared_url, RECENT)]),
            fake_feed([rss_entry("Article", shared_url, RECENT)]),
        ]
    )
    with patch("pipeline.discovery.httpx.AsyncClient", return_value=mock_rss_client()):
        with patch("pipeline.discovery.feedparser.parse", side_effect=lambda _: next(feeds)):
            articles = await discover(p)
    assert len(articles) == 1
    assert articles[0]["url"] == shared_url


# --- inactive sources ---


async def test_skips_inactive_sources(tmp_path):
    p = write_sources(tmp_path, [INACTIVE, RSS_SOURCE])
    fetched_urls: list[str] = []

    ok_resp = MagicMock()
    ok_resp.raise_for_status = MagicMock()
    ok_resp.content = b""

    async def fake_get(url, **kwargs):
        fetched_urls.append(str(url))
        return ok_resp

    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get = fake_get

    with patch("pipeline.discovery.httpx.AsyncClient", return_value=client):
        with patch(
            "pipeline.discovery.feedparser.parse",
            return_value=fake_feed([rss_entry("Art", "http://ex.com/art", RECENT)]),
        ):
            articles = await discover(p)

    assert INACTIVE["url"] not in fetched_urls
    assert len(articles) == 1


async def test_all_inactive_returns_empty(tmp_path):
    p = write_sources(tmp_path, [INACTIVE])
    with patch("pipeline.discovery.feedparser.parse") as mock_parse:
        articles = await discover(p)
    mock_parse.assert_not_called()
    assert articles == []


# --- failed source is skipped ---


async def test_failed_source_does_not_block_others(tmp_path):
    src_a = {"name": "A", "url": "http://a.com/feed", "type": "rss", "active": True}
    src_b = {"name": "B", "url": "http://b.com/feed", "type": "rss", "active": True}
    p = write_sources(tmp_path, [src_a, src_b])
    good_feed = fake_feed([rss_entry("Good", "http://ex.com/good", RECENT)])
    with patch(
        "pipeline.discovery.httpx.AsyncClient",
        return_value=mock_rss_client(url_to_raise=src_a["url"]),
    ):
        with patch("pipeline.discovery.feedparser.parse", return_value=good_feed):
            articles = await discover(p)
    assert len(articles) == 1
    assert articles[0]["title"] == "Good"
