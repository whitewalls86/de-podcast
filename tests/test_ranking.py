import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pipeline.ranking import rank


def make_articles(n: int, base_url: str = "http://example.com/") -> list[dict]:
    return [
        {
            "title": f"Article {i}",
            "url": f"{base_url}{i}",
            "source": "Test",
            "published_at": "2024-01-01T00:00:00+00:00",
            "snippet": f"Snippet {i}",
        }
        for i in range(n)
    ]


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


async def test_score_merge_by_url(monkeypatch):
    articles = make_articles(3)
    scores = [
        {"url": articles[0]["url"], "score": 0.9, "topic_tags": ["dbt"], "reason": "great"},
        {"url": articles[1]["url"], "score": 0.7, "topic_tags": ["kafka"], "reason": "good"},
        {"url": articles[2]["url"], "score": 0.3, "topic_tags": [], "reason": "meh"},
    ]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch(
        "pipeline.ranking.anthropic.AsyncAnthropic", return_value=mock_client(json.dumps(scores))
    ):
        result = await rank(articles)
    urls = [a["url"] for a in result]
    assert articles[0]["url"] in urls
    assert articles[1]["url"] in urls
    assert articles[2]["url"] not in urls
    assert result[0]["score"] == 0.9
    assert result[0]["reason"] == "great"
    assert result[0]["topic_tags"] == ["dbt"]


async def test_topic_tags_preserved(monkeypatch):
    articles = make_articles(2)
    scores = [
        {"url": articles[0]["url"], "score": 0.8, "topic_tags": ["spark", "delta"], "reason": "x"},
        {"url": articles[1]["url"], "score": 0.6, "topic_tags": [], "reason": "y"},
    ]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch(
        "pipeline.ranking.anthropic.AsyncAnthropic", return_value=mock_client(json.dumps(scores))
    ):
        result = await rank(articles)
    assert result[0]["topic_tags"] == ["spark", "delta"]
    assert result[1]["topic_tags"] == []


async def test_topic_tags_defaults_to_empty_list_when_absent(monkeypatch):
    articles = make_articles(1)
    scores = [{"url": articles[0]["url"], "score": 0.8, "reason": "no tags field"}]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch(
        "pipeline.ranking.anthropic.AsyncAnthropic", return_value=mock_client(json.dumps(scores))
    ):
        result = await rank(articles)
    assert result[0]["topic_tags"] == []


async def test_score_filtering_drops_below_threshold(monkeypatch):
    articles = make_articles(3)
    scores = [
        {"url": articles[0]["url"], "score": 0.5, "reason": "ok"},
        {"url": articles[1]["url"], "score": 0.49, "reason": "just below"},
        {"url": articles[2]["url"], "score": 0.0, "reason": "bad"},
    ]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch(
        "pipeline.ranking.anthropic.AsyncAnthropic", return_value=mock_client(json.dumps(scores))
    ):
        result = await rank(articles)
    assert len(result) == 1
    assert result[0]["url"] == articles[0]["url"]


async def test_top_10_cap(monkeypatch):
    articles = make_articles(15)
    scores = [
        {"url": articles[i]["url"], "score": round(0.9 - i * 0.01, 2), "reason": "ok"}
        for i in range(15)
    ]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch(
        "pipeline.ranking.anthropic.AsyncAnthropic", return_value=mock_client(json.dumps(scores))
    ):
        result = await rank(articles)
    assert len(result) == 10


async def test_sorted_descending(monkeypatch):
    articles = make_articles(3)
    scores = [
        {"url": articles[0]["url"], "score": 0.6, "reason": "ok"},
        {"url": articles[1]["url"], "score": 0.9, "reason": "great"},
        {"url": articles[2]["url"], "score": 0.75, "reason": "good"},
    ]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch(
        "pipeline.ranking.anthropic.AsyncAnthropic", return_value=mock_client(json.dumps(scores))
    ):
        result = await rank(articles)
    output_scores = [a["score"] for a in result]
    assert output_scores == sorted(output_scores, reverse=True)


async def test_invalid_json_raises(monkeypatch):
    articles = make_articles(2)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch(
        "pipeline.ranking.anthropic.AsyncAnthropic", return_value=mock_client("not valid json {{")
    ):
        with pytest.raises(ValueError, match="invalid JSON"):
            await rank(articles)


async def test_empty_articles_skips_api_call(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    result = await rank([])
    assert result == []


async def test_wrong_top_level_type_raises(monkeypatch):
    articles = make_articles(2)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch("pipeline.ranking.anthropic.AsyncAnthropic", return_value=mock_client("{}")):
        with pytest.raises(ValueError, match="JSON array"):
            await rank(articles)


async def test_entry_missing_url_raises(monkeypatch):
    articles = make_articles(1)
    scores = [{"score": 0.9, "reason": "ok"}]  # no url
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch(
        "pipeline.ranking.anthropic.AsyncAnthropic", return_value=mock_client(json.dumps(scores))
    ):
        with pytest.raises(ValueError, match="string 'url'"):
            await rank(articles)


async def test_entry_non_numeric_score_raises(monkeypatch):
    articles = make_articles(1)
    scores = [{"url": articles[0]["url"], "score": "high", "reason": "ok"}]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch(
        "pipeline.ranking.anthropic.AsyncAnthropic", return_value=mock_client(json.dumps(scores))
    ):
        with pytest.raises(ValueError, match="'score' must be a float in"):
            await rank(articles)


async def test_score_above_1_raises(monkeypatch):
    articles = make_articles(1)
    scores = [{"url": articles[0]["url"], "score": 2.0, "reason": "ok"}]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch(
        "pipeline.ranking.anthropic.AsyncAnthropic", return_value=mock_client(json.dumps(scores))
    ):
        with pytest.raises(ValueError, match="'score' must be a float in"):
            await rank(articles)


async def test_score_below_0_raises(monkeypatch):
    articles = make_articles(1)
    scores = [{"url": articles[0]["url"], "score": -0.1, "reason": "ok"}]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch(
        "pipeline.ranking.anthropic.AsyncAnthropic", return_value=mock_client(json.dumps(scores))
    ):
        with pytest.raises(ValueError, match="'score' must be a float in"):
            await rank(articles)


async def test_score_as_bool_raises(monkeypatch):
    articles = make_articles(1)
    # True is int subclass with value 1, which would pass a plain numeric check
    scores = [{"url": articles[0]["url"], "score": True, "reason": "ok"}]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch(
        "pipeline.ranking.anthropic.AsyncAnthropic", return_value=mock_client(json.dumps(scores))
    ):
        with pytest.raises(ValueError, match="'score' must be a float in"):
            await rank(articles)
