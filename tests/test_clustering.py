import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pipeline.clustering import cluster


def make_articles(urls: list[str]) -> list[dict]:
    return [{"title": f"Article {u}", "url": u, "source": "Test", "snippet": ""} for u in urls]


def mock_client(text: str):
    content_block = MagicMock()
    content_block.text = text
    response = MagicMock()
    response.content = [content_block]
    messages = AsyncMock()
    messages.create = AsyncMock(return_value=response)
    client = MagicMock()
    client.messages = messages
    return client


async def test_all_urls_assigned(monkeypatch):
    urls = [f"http://example.com/{i}" for i in range(5)]
    articles = make_articles(urls)
    cluster_result = {
        "batch_a": {"title": "Batch A", "urls": urls[:3]},
        "batch_b": {"title": "Batch B", "urls": urls[3:]},
    }
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch(
        "pipeline.clustering.anthropic.AsyncAnthropic",
        return_value=mock_client(json.dumps(cluster_result)),
    ):
        result = await cluster(articles)
    all_urls = set(result["batch_a"]["urls"]) | set(result["batch_b"]["urls"])
    assert all_urls == set(urls)


async def test_exactly_two_batches(monkeypatch):
    urls = [f"http://example.com/{i}" for i in range(4)]
    articles = make_articles(urls)
    cluster_result = {
        "batch_a": {"title": "A", "urls": urls[:2]},
        "batch_b": {"title": "B", "urls": urls[2:]},
    }
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch(
        "pipeline.clustering.anthropic.AsyncAnthropic",
        return_value=mock_client(json.dumps(cluster_result)),
    ):
        result = await cluster(articles)
    assert set(result.keys()) == {"batch_a", "batch_b"}


async def test_batch_titles_present(monkeypatch):
    urls = ["http://a.com/1", "http://b.com/2"]
    articles = make_articles(urls)
    cluster_result = {
        "batch_a": {"title": "Streaming", "urls": [urls[0]]},
        "batch_b": {"title": "Batch Processing", "urls": [urls[1]]},
    }
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch(
        "pipeline.clustering.anthropic.AsyncAnthropic",
        return_value=mock_client(json.dumps(cluster_result)),
    ):
        result = await cluster(articles)
    assert result["batch_a"]["title"] == "Streaming"
    assert result["batch_b"]["title"] == "Batch Processing"


async def test_invalid_json_raises(monkeypatch):
    articles = make_articles(["http://example.com/1"])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch(
        "pipeline.clustering.anthropic.AsyncAnthropic", return_value=mock_client("not json {{{")
    ):
        with pytest.raises(ValueError, match="invalid JSON"):
            await cluster(articles)
