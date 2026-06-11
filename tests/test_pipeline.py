import json
from unittest.mock import AsyncMock, patch

from pipeline.pipeline import run_pipeline

_ARTICLES = [
    {"title": "Article A", "url": "http://example.com/a", "source": "s", "snippet": ""},
    {"title": "Article B", "url": "http://example.com/b", "source": "s", "snippet": ""},
    {"title": "Article C", "url": "http://example.com/c", "source": "s", "snippet": ""},
]

_RANKED = [{**a, "score": 0.9, "topic_tags": [], "reason": ""} for a in _ARTICLES]

_CLUSTERS = {
    "batch_a": {"title": "Streaming", "urls": ["http://example.com/a", "http://example.com/b"]},
    "batch_b": {"title": "Batch", "urls": ["http://example.com/c"]},
}


async def _fake_generate(batch_key: str, title: str, urls: list[str]) -> str:
    return f"data/{batch_key}.mp3"


def _patch_stages(articles=_ARTICLES, ranked=_RANKED, clusters=_CLUSTERS):
    return [
        patch("pipeline.pipeline.discover", new=AsyncMock(return_value=articles)),
        patch("pipeline.pipeline.rank", new=AsyncMock(return_value=ranked)),
        patch("pipeline.pipeline.cluster", new=AsyncMock(return_value=clusters)),
    ]


async def test_result_shape(tmp_path):
    sources = tmp_path / "sources.json"
    sources.write_text("[]")
    seen = tmp_path / "seen_urls.json"

    patches = _patch_stages()
    for p in patches:
        p.start()
    try:
        result = await run_pipeline(
            sources_path=sources, seen_path=seen, generate_fn=_fake_generate
        )
    finally:
        for p in patches:
            p.stop()

    assert result["status"] == "success"
    assert "batches" in result
    assert "articles_seen" in result
    assert len(result["batches"]) == 2
    assert result["batches"][0]["title"] == "Streaming"
    assert result["batches"][0]["mp3"] == "data/batch_a.mp3"


async def test_dedup_filters_seen_urls(tmp_path):
    sources = tmp_path / "sources.json"
    sources.write_text("[]")
    seen = tmp_path / "seen_urls.json"
    seen.write_text(json.dumps(["http://example.com/a"]))

    captured = {}

    async def capturing_rank(articles, **kwargs):
        captured["urls"] = [a["url"] for a in articles]
        return _RANKED

    patches = [
        patch("pipeline.pipeline.discover", new=AsyncMock(return_value=_ARTICLES)),
        patch("pipeline.pipeline.rank", new=capturing_rank),
        patch("pipeline.pipeline.cluster", new=AsyncMock(return_value=_CLUSTERS)),
    ]
    for p in patches:
        p.start()
    try:
        await run_pipeline(sources_path=sources, seen_path=seen, generate_fn=_fake_generate)
    finally:
        for p in patches:
            p.stop()

    assert "http://example.com/a" not in captured["urls"]
    assert "http://example.com/b" in captured["urls"]


async def test_seen_urls_written_on_success(tmp_path):
    sources = tmp_path / "sources.json"
    sources.write_text("[]")
    seen = tmp_path / "seen_urls.json"

    patches = _patch_stages()
    for p in patches:
        p.start()
    try:
        await run_pipeline(sources_path=sources, seen_path=seen, generate_fn=_fake_generate)
    finally:
        for p in patches:
            p.stop()

    written = set(json.loads(seen.read_text()))
    assert written == {"http://example.com/a", "http://example.com/b", "http://example.com/c"}


async def test_seen_urls_not_written_on_generation_failure(tmp_path):
    sources = tmp_path / "sources.json"
    sources.write_text("[]")
    seen = tmp_path / "seen_urls.json"

    async def always_fail(batch_key, title, urls):
        raise RuntimeError("generation error")

    patches = _patch_stages()
    for p in patches:
        p.start()
    try:
        result = await run_pipeline(sources_path=sources, seen_path=seen, generate_fn=always_fail)
    finally:
        for p in patches:
            p.stop()

    assert not seen.exists()
    assert result["status"] == "failed"
    assert result["batches"] == []


async def test_partial_failure_does_not_block_other_batch(tmp_path):
    sources = tmp_path / "sources.json"
    sources.write_text("[]")
    seen = tmp_path / "seen_urls.json"

    async def fail_batch_a(batch_key, title, urls):
        if batch_key == "batch_a":
            raise RuntimeError("batch_a failed")
        return f"data/{batch_key}.mp3"

    patches = _patch_stages()
    for p in patches:
        p.start()
    try:
        result = await run_pipeline(sources_path=sources, seen_path=seen, generate_fn=fail_batch_a)
    finally:
        for p in patches:
            p.stop()

    assert result["status"] == "partial"
    assert len(result["batches"]) == 1
    assert result["batches"][0]["title"] == "Batch"
    # only URLs from the successful batch should be marked seen
    written = set(json.loads(seen.read_text()))
    assert written == set(_CLUSTERS["batch_b"]["urls"])
    assert not written.intersection(_CLUSTERS["batch_a"]["urls"])


async def test_fewer_than_two_ranked_returns_no_op(tmp_path):
    sources = tmp_path / "sources.json"
    sources.write_text("[]")
    seen = tmp_path / "seen_urls.json"

    one_article = _RANKED[:1]
    patches = [
        patch("pipeline.pipeline.discover", new=AsyncMock(return_value=_ARTICLES)),
        patch("pipeline.pipeline.rank", new=AsyncMock(return_value=one_article)),
    ]
    for p in patches:
        p.start()
    try:
        result = await run_pipeline(
            sources_path=sources, seen_path=seen, generate_fn=_fake_generate
        )
    finally:
        for p in patches:
            p.stop()

    assert result == {"status": "noop", "batches": [], "articles_seen": 0}
    assert not seen.exists()


async def test_feedback_path_forwarded_to_rank(tmp_path):
    sources = tmp_path / "sources.json"
    sources.write_text("[]")
    custom_feedback = tmp_path / "custom_feedback.json"
    captured = {}

    async def capturing_rank(articles, **kwargs):
        captured["feedback_path"] = kwargs.get("feedback_path")
        return _RANKED

    patches = [
        patch("pipeline.pipeline.discover", new=AsyncMock(return_value=_ARTICLES)),
        patch("pipeline.pipeline.rank", new=capturing_rank),
        patch("pipeline.pipeline.cluster", new=AsyncMock(return_value=_CLUSTERS)),
    ]
    for p in patches:
        p.start()
    try:
        await run_pipeline(
            sources_path=sources,
            seen_path=tmp_path / "seen.json",
            feedback_path=custom_feedback,
            generate_fn=_fake_generate,
        )
    finally:
        for p in patches:
            p.stop()

    assert captured["feedback_path"] == custom_feedback


async def test_seen_file_created_if_absent(tmp_path):
    sources = tmp_path / "sources.json"
    sources.write_text("[]")
    seen = tmp_path / "subdir" / "seen_urls.json"

    patches = _patch_stages()
    for p in patches:
        p.start()
    try:
        await run_pipeline(sources_path=sources, seen_path=seen, generate_fn=_fake_generate)
    finally:
        for p in patches:
            p.stop()

    assert seen.exists()


# --- feed posting (step 6) ---

from unittest.mock import MagicMock  # noqa: E402

from pipeline.pipeline import _post_to_feed  # noqa: E402


async def test_run_pipeline_posts_each_successful_batch(tmp_path):
    sources = tmp_path / "sources.json"
    sources.write_text("[]")
    seen = tmp_path / "seen_urls.json"

    post_mock = AsyncMock()
    patches = _patch_stages() + [patch("pipeline.pipeline._post_to_feed", new=post_mock)]
    for p in patches:
        p.start()
    try:
        await run_pipeline(sources_path=sources, seen_path=seen, generate_fn=_fake_generate)
    finally:
        for p in patches:
            p.stop()

    assert post_mock.await_count == len(_CLUSTERS)
    posted_ids = {c.kwargs["episode_id"] for c in post_mock.await_args_list}
    assert any(eid.startswith("streaming-") for eid in posted_ids)


async def test_post_to_feed_sends_correct_multipart_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("FEED_URL", "http://feed:8000")
    monkeypatch.setenv("FEED_TOKEN", "secret")
    mp3 = tmp_path / "episode.mp3"
    mp3.write_bytes(b"ID3 fake mp3 bytes")

    resp = MagicMock(status_code=200)
    client = AsyncMock()
    client.post = AsyncMock(return_value=resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)

    with patch("pipeline.pipeline.httpx.AsyncClient", return_value=cm):
        await _post_to_feed(
            mp3_path=str(mp3),
            title="Streaming Pipelines",
            episode_id="streaming-pipelines-2026-06-10",
            topic_tags=["streaming", "kafka"],
        )

    call = client.post.call_args
    assert call.args[0] == "http://feed:8000/episodes"
    data = call.kwargs["data"]
    assert data["title"] == "Streaming Pipelines"
    assert data["episode_id"] == "streaming-pipelines-2026-06-10"
    assert data["tags"] == "streaming,kafka"
    assert data["description"] == ""
    assert "file" in call.kwargs["files"]
    assert call.kwargs["headers"]["Authorization"] == "Bearer secret"


async def test_ranked_tags_flow_to_feed_post(tmp_path):
    sources = tmp_path / "sources.json"
    sources.write_text("[]")
    seen = tmp_path / "seen_urls.json"

    # Article A → kafka + streaming, Article B → dbt, Article C → spark
    ranked_with_tags = [
        {**a, "score": 0.9, "reason": "", "topic_tags": tags}
        for a, tags in zip(
            _ARTICLES,
            [["kafka", "streaming"], ["dbt"], ["spark"]],
        )
    ]
    # batch_a has URLs a+b → union {kafka, streaming, dbt}
    # batch_b has URL c   → {spark}

    post_mock = AsyncMock()
    patches = [
        patch("pipeline.pipeline.discover", new=AsyncMock(return_value=_ARTICLES)),
        patch("pipeline.pipeline.rank", new=AsyncMock(return_value=ranked_with_tags)),
        patch("pipeline.pipeline.cluster", new=AsyncMock(return_value=_CLUSTERS)),
        patch("pipeline.pipeline._post_to_feed", new=post_mock),
    ]
    for p in patches:
        p.start()
    try:
        await run_pipeline(sources_path=sources, seen_path=seen, generate_fn=_fake_generate)
    finally:
        for p in patches:
            p.stop()

    by_title = {c.kwargs["title"]: c.kwargs["topic_tags"] for c in post_mock.await_args_list}
    assert set(by_title["Streaming"]) == {"kafka", "streaming", "dbt"}
    assert set(by_title["Batch"]) == {"spark"}


async def test_feed_post_failure_marks_batch_failed(tmp_path):
    sources = tmp_path / "sources.json"
    sources.write_text("[]")
    seen = tmp_path / "seen_urls.json"

    failing_post = AsyncMock(side_effect=RuntimeError("feed down"))
    patches = _patch_stages() + [patch("pipeline.pipeline._post_to_feed", new=failing_post)]
    for p in patches:
        p.start()
    try:
        result = await run_pipeline(
            sources_path=sources, seen_path=seen, generate_fn=_fake_generate
        )
    finally:
        for p in patches:
            p.stop()

    assert result["status"] == "failed"
    assert result["batches"] == []
    assert not seen.exists()
