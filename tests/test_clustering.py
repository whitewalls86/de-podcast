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
    with patch(
        "pipeline.clustering.get_anthropic_client",
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
    with patch(
        "pipeline.clustering.get_anthropic_client",
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
    with patch(
        "pipeline.clustering.get_anthropic_client",
        return_value=mock_client(json.dumps(cluster_result)),
    ):
        result = await cluster(articles)
    assert result["batch_a"]["title"] == "Streaming"
    assert result["batch_b"]["title"] == "Batch Processing"


async def test_url_normalization_remaps_claude_modified_urls(monkeypatch):
    # Claude sometimes changes underscores to hyphens in URLs (e.g. Reddit slugs).
    # The remapping step should restore the canonical input URL.
    canonical = "https://reddit.com/r/de/comments/abc/my_article_title/"
    normalized = "https://reddit.com/r/de/comments/abc/my-article-title/"
    articles = make_articles([canonical, "http://example.com/2"])
    cluster_result = {
        "batch_a": {"title": "A", "urls": [normalized]},  # Claude changed _ to -
        "batch_b": {"title": "B", "urls": ["http://example.com/2"]},
    }
    with patch(
        "pipeline.clustering.get_anthropic_client",
        return_value=mock_client(json.dumps(cluster_result)),
    ):
        result = await cluster(articles)
    assert canonical in result["batch_a"]["urls"]
    assert normalized not in result["batch_a"]["urls"]


async def test_fenced_json_is_parsed(monkeypatch):
    urls = ["http://example.com/1", "http://example.com/2"]
    articles = make_articles(urls)
    cluster_result = {
        "batch_a": {"title": "A", "urls": [urls[0]]},
        "batch_b": {"title": "B", "urls": [urls[1]]},
    }
    fenced = f"```json\n{json.dumps(cluster_result)}\n```"
    with patch("pipeline.clustering.get_anthropic_client", return_value=mock_client(fenced)):
        result = await cluster(articles)
    assert result["batch_a"]["title"] == "A"


async def test_invalid_json_raises(monkeypatch):
    articles = make_articles(["http://example.com/1", "http://example.com/2"])
    with patch(
        "pipeline.clustering.get_anthropic_client", return_value=mock_client("not json {{{")
    ):
        with pytest.raises(ValueError, match="invalid JSON"):
            await cluster(articles)


async def test_wrong_top_level_type_raises(monkeypatch):
    articles = make_articles(["http://example.com/1", "http://example.com/2"])
    with patch("pipeline.clustering.get_anthropic_client", return_value=mock_client("[]")):
        with pytest.raises(ValueError, match="JSON object"):
            await cluster(articles)


async def test_urls_not_a_list_raises(monkeypatch):
    urls = ["http://example.com/1", "http://example.com/2"]
    articles = make_articles(urls)
    cluster_result = {
        "batch_a": {"title": "A", "urls": {"http://example.com/1": True}},  # dict, not list
        "batch_b": {"title": "B", "urls": [urls[1]]},
    }
    with patch(
        "pipeline.clustering.get_anthropic_client",
        return_value=mock_client(json.dumps(cluster_result)),
    ):
        with pytest.raises(ValueError, match="list of strings"):
            await cluster(articles)


async def test_urls_with_non_string_elements_raises(monkeypatch):
    urls = ["http://example.com/1", "http://example.com/2"]
    articles = make_articles(urls)
    cluster_result = {
        "batch_a": {"title": "A", "urls": [urls[0], 42]},
        "batch_b": {"title": "B", "urls": [urls[1]]},
    }
    with patch(
        "pipeline.clustering.get_anthropic_client",
        return_value=mock_client(json.dumps(cluster_result)),
    ):
        with pytest.raises(ValueError, match="list of strings"):
            await cluster(articles)


async def test_batch_value_not_dict_raises(monkeypatch):
    urls = ["http://example.com/1", "http://example.com/2"]
    articles = make_articles(urls)
    cluster_result = {"batch_a": [], "batch_b": {"title": "B", "urls": [urls[1]]}}
    with patch(
        "pipeline.clustering.get_anthropic_client",
        return_value=mock_client(json.dumps(cluster_result)),
    ):
        with pytest.raises(ValueError, match="must be an object"):
            await cluster(articles)


async def test_missing_url_raises(monkeypatch):
    urls = ["http://example.com/1", "http://example.com/2", "http://example.com/3"]
    articles = make_articles(urls)
    cluster_result = {
        "batch_a": {"title": "A", "urls": [urls[0]]},
        "batch_b": {"title": "B", "urls": [urls[1]]},  # urls[2] omitted
    }
    with patch(
        "pipeline.clustering.get_anthropic_client",
        return_value=mock_client(json.dumps(cluster_result)),
    ):
        with pytest.raises(ValueError, match="mismatch"):
            await cluster(articles)


async def test_duplicate_url_across_batches_raises(monkeypatch):
    urls = ["http://example.com/1", "http://example.com/2"]
    articles = make_articles(urls)
    cluster_result = {
        "batch_a": {"title": "A", "urls": urls},
        "batch_b": {"title": "B", "urls": [urls[0]]},  # urls[0] duplicated
    }
    with patch(
        "pipeline.clustering.get_anthropic_client",
        return_value=mock_client(json.dumps(cluster_result)),
    ):
        with pytest.raises(ValueError, match="duplicated"):
            await cluster(articles)


async def test_wrong_batch_keys_raises(monkeypatch):
    urls = ["http://example.com/1", "http://example.com/2"]
    articles = make_articles(urls)
    cluster_result = {
        "batch_a": {"title": "A", "urls": [urls[0]]},
        "batch_c": {"title": "C", "urls": [urls[1]]},  # wrong key
    }
    with patch(
        "pipeline.clustering.get_anthropic_client",
        return_value=mock_client(json.dumps(cluster_result)),
    ):
        with pytest.raises(ValueError, match="batch_a and batch_b"):
            await cluster(articles)


async def test_empty_batch_raises(monkeypatch):
    urls = ["http://example.com/1", "http://example.com/2"]
    articles = make_articles(urls)
    cluster_result = {
        "batch_a": {"title": "A", "urls": urls},
        "batch_b": {"title": "B", "urls": []},  # empty
    }
    with patch(
        "pipeline.clustering.get_anthropic_client",
        return_value=mock_client(json.dumps(cluster_result)),
    ):
        with pytest.raises(ValueError, match="empty URL list"):
            await cluster(articles)


async def test_missing_title_raises(monkeypatch):
    urls = ["http://example.com/1", "http://example.com/2"]
    articles = make_articles(urls)
    cluster_result = {
        "batch_a": {"urls": [urls[0]]},  # no title key
        "batch_b": {"title": "B", "urls": [urls[1]]},
    }
    with patch(
        "pipeline.clustering.get_anthropic_client",
        return_value=mock_client(json.dumps(cluster_result)),
    ):
        with pytest.raises(ValueError, match="empty title"):
            await cluster(articles)


async def test_empty_title_raises(monkeypatch):
    urls = ["http://example.com/1", "http://example.com/2"]
    articles = make_articles(urls)
    cluster_result = {
        "batch_a": {"title": "   ", "urls": [urls[0]]},  # whitespace-only
        "batch_b": {"title": "B", "urls": [urls[1]]},
    }
    with patch(
        "pipeline.clustering.get_anthropic_client",
        return_value=mock_client(json.dumps(cluster_result)),
    ):
        with pytest.raises(ValueError, match="empty title"):
            await cluster(articles)


async def test_fewer_than_two_articles_raises():
    with pytest.raises(ValueError, match="at least 2 articles"):
        await cluster([])
    with pytest.raises(ValueError, match="at least 2 articles"):
        await cluster(make_articles(["http://example.com/1"]))
