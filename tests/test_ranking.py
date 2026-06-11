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
    with patch(
        "pipeline.ranking.get_anthropic_client", return_value=mock_client(json.dumps(scores))
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
    with patch(
        "pipeline.ranking.get_anthropic_client", return_value=mock_client(json.dumps(scores))
    ):
        result = await rank(articles)
    assert result[0]["topic_tags"] == ["spark", "delta"]
    assert result[1]["topic_tags"] == []


async def test_topic_tags_defaults_to_empty_list_when_absent(monkeypatch):
    articles = make_articles(1)
    scores = [{"url": articles[0]["url"], "score": 0.8, "reason": "no tags field"}]
    with patch(
        "pipeline.ranking.get_anthropic_client", return_value=mock_client(json.dumps(scores))
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
    with patch(
        "pipeline.ranking.get_anthropic_client", return_value=mock_client(json.dumps(scores))
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
    with patch(
        "pipeline.ranking.get_anthropic_client", return_value=mock_client(json.dumps(scores))
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
    with patch(
        "pipeline.ranking.get_anthropic_client", return_value=mock_client(json.dumps(scores))
    ):
        result = await rank(articles)
    output_scores = [a["score"] for a in result]
    assert output_scores == sorted(output_scores, reverse=True)


async def test_fenced_json_is_parsed(monkeypatch):
    articles = make_articles(2)
    scores = [{"url": a["url"], "score": 0.9, "reason": "ok"} for a in articles]
    fenced = f"```json\n{json.dumps(scores)}\n```"
    with patch("pipeline.ranking.get_anthropic_client", return_value=mock_client(fenced)):
        result = await rank(articles)
    assert len(result) == 2


async def test_fenced_json_with_trailing_newline_is_parsed(monkeypatch):
    articles = make_articles(2)
    scores = [{"url": a["url"], "score": 0.9, "reason": "ok"} for a in articles]
    fenced = f"```json\n{json.dumps(scores)}\n```\n"
    with patch("pipeline.ranking.get_anthropic_client", return_value=mock_client(fenced)):
        result = await rank(articles)
    assert len(result) == 2


async def test_invalid_json_raises(monkeypatch):
    articles = make_articles(2)
    with patch(
        "pipeline.ranking.get_anthropic_client", return_value=mock_client("not valid json {{")
    ):
        with pytest.raises(ValueError, match="invalid JSON"):
            await rank(articles)


async def test_truncated_fenced_json_raises_clearly(monkeypatch):
    # Simulates Anthropic truncating mid-response (no closing fence, incomplete JSON)
    articles = make_articles(2)
    truncated = '```json\n[{"url": "http://example.com/0", "score": 0.9'
    with patch("pipeline.ranking.get_anthropic_client", return_value=mock_client(truncated)):
        with pytest.raises(ValueError, match="invalid JSON"):
            await rank(articles)


async def test_empty_articles_skips_api_call():
    result = await rank([])
    assert result == []


async def test_wrong_top_level_type_raises(monkeypatch):
    articles = make_articles(2)
    with patch("pipeline.ranking.get_anthropic_client", return_value=mock_client("{}")):
        with pytest.raises(ValueError, match="JSON array"):
            await rank(articles)


async def test_entry_missing_url_raises(monkeypatch):
    articles = make_articles(1)
    scores = [{"score": 0.9, "reason": "ok"}]  # no url
    with patch(
        "pipeline.ranking.get_anthropic_client", return_value=mock_client(json.dumps(scores))
    ):
        with pytest.raises(ValueError, match="string 'url'"):
            await rank(articles)


async def test_entry_non_numeric_score_raises(monkeypatch):
    articles = make_articles(1)
    scores = [{"url": articles[0]["url"], "score": "high", "reason": "ok"}]
    with patch(
        "pipeline.ranking.get_anthropic_client", return_value=mock_client(json.dumps(scores))
    ):
        with pytest.raises(ValueError, match="'score' must be a float in"):
            await rank(articles)


async def test_score_above_1_raises(monkeypatch):
    articles = make_articles(1)
    scores = [{"url": articles[0]["url"], "score": 2.0, "reason": "ok"}]
    with patch(
        "pipeline.ranking.get_anthropic_client", return_value=mock_client(json.dumps(scores))
    ):
        with pytest.raises(ValueError, match="'score' must be a float in"):
            await rank(articles)


async def test_score_below_0_raises(monkeypatch):
    articles = make_articles(1)
    scores = [{"url": articles[0]["url"], "score": -0.1, "reason": "ok"}]
    with patch(
        "pipeline.ranking.get_anthropic_client", return_value=mock_client(json.dumps(scores))
    ):
        with pytest.raises(ValueError, match="'score' must be a float in"):
            await rank(articles)


async def test_topic_tags_as_string_raises(monkeypatch):
    articles = make_articles(1)
    scores = [{"url": articles[0]["url"], "score": 0.8, "topic_tags": "dbt"}]
    with patch(
        "pipeline.ranking.get_anthropic_client", return_value=mock_client(json.dumps(scores))
    ):
        with pytest.raises(ValueError, match="array of strings"):
            await rank(articles)


async def test_topic_tags_with_non_string_elements_raises(monkeypatch):
    articles = make_articles(1)
    scores = [{"url": articles[0]["url"], "score": 0.8, "topic_tags": ["dbt", 42]}]
    with patch(
        "pipeline.ranking.get_anthropic_client", return_value=mock_client(json.dumps(scores))
    ):
        with pytest.raises(ValueError, match="array of strings"):
            await rank(articles)


async def test_score_as_bool_raises(monkeypatch):
    articles = make_articles(1)
    # True is int subclass with value 1, which would pass a plain numeric check
    scores = [{"url": articles[0]["url"], "score": True, "reason": "ok"}]
    with patch(
        "pipeline.ranking.get_anthropic_client", return_value=mock_client(json.dumps(scores))
    ):
        with pytest.raises(ValueError, match="'score' must be a float in"):
            await rank(articles)


# --- build_ranking_prompt ---

from pipeline.ranking import build_ranking_prompt  # noqa: E402


def test_build_ranking_prompt_without_few_shot_omits_preference_section():
    articles = make_articles(2)
    prompt = build_ranking_prompt(articles, "")
    assert "Liked:" not in prompt
    assert "Disliked:" not in prompt
    assert "Score these articles:" in prompt


def test_build_ranking_prompt_with_few_shot_includes_it():
    articles = make_articles(2)
    few_shot = 'User feedback on past episodes:\nLiked:\n  - "Great" [tags: dbt]'
    prompt = build_ranking_prompt(articles, few_shot)
    assert few_shot in prompt
    assert "Score these articles:" in prompt
    assert prompt.index(few_shot) < prompt.index("Score these articles:")


async def test_rank_with_feedback_passes_context_to_prompt(tmp_path):
    feedback = tmp_path / "feedback.json"
    entries = [
        {
            "episode_id": f"ep-{i}",
            "title": f"Great Episode {i}",
            "topic_tags": ["dbt"],
            "article_urls": [],
            "vote": "up",
            "timestamp": "2026-06-10T08:00:00Z",
        }
        for i in range(3)
    ]
    feedback.write_text(json.dumps(entries))

    articles = make_articles(2)
    scores = [{"url": a["url"], "score": 0.9, "reason": "ok"} for a in articles]
    client = mock_client(json.dumps(scores))

    with patch("pipeline.ranking.get_anthropic_client", return_value=client):
        await rank(articles, feedback_path=feedback)

    call_kwargs = client.messages.create.call_args.kwargs
    user_content = call_kwargs["messages"][0]["content"]
    assert "Liked:" in user_content
