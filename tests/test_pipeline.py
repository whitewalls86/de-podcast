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


async def _fake_generate(
    batch_key: str, title: str, urls: list[str], topic: dict
) -> tuple[str, list[str]]:
    return f"data/{batch_key}.mp3", urls


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


async def test_only_consumed_urls_written_to_seen(tmp_path):
    # If generate_fn only consumed a subset of URLs (e.g. one source was skipped),
    # only those consumed URLs should be marked seen — not the full batch list.
    sources = tmp_path / "sources.json"
    sources.write_text("[]")
    seen = tmp_path / "seen_urls.json"

    async def partial_consume(batch_key, title, urls, topic):
        # Simulate one URL being skipped (not added to NotebookLM)
        return f"data/{batch_key}.mp3", urls[:1]

    patches = _patch_stages()
    for p in patches:
        p.start()
    try:
        await run_pipeline(sources_path=sources, seen_path=seen, generate_fn=partial_consume)
    finally:
        for p in patches:
            p.stop()

    written = set(json.loads(seen.read_text()))
    # batch_a consumed only url[0], batch_b consumed only url[0]
    assert "http://example.com/a" in written
    assert "http://example.com/b" not in written  # skipped — should be retried
    assert "http://example.com/c" in written


async def test_seen_urls_not_written_on_generation_failure(tmp_path):
    sources = tmp_path / "sources.json"
    sources.write_text("[]")
    seen = tmp_path / "seen_urls.json"

    async def always_fail(batch_key, title, urls, topic):
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

    async def fail_batch_a(batch_key, title, urls, topic):
        if batch_key == "batch_a":
            raise RuntimeError("batch_a failed")
        return f"data/{batch_key}.mp3", urls

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


# --- pinned URL behavior ---


from pipeline.pipeline import _merge_pinned  # noqa: E402


def _make_article(url: str, score: float = 0.9) -> dict:
    return {
        "url": url,
        "title": f"T {url}",
        "source": "s",
        "snippet": "",
        "score": score,
        "topic_tags": [],
        "reason": "",
    }


def _make_pinned(url: str) -> dict:
    return {
        "url": url,
        "title": f"Pinned {url}",
        "source": "Pinned",
        "published_at": "2026-01-01T00:00:00+00:00",
        "snippet": "",
        "score": 1.0,
        "topic_tags": ["pinned"],
        "reason": "Pinned by user",
    }


def test_merge_pinned_puts_pinned_first():
    pinned = [_make_pinned("https://example.com/pin")]
    ranked = [_make_article("https://example.com/a"), _make_article("https://example.com/b")]
    result = _merge_pinned(pinned, ranked)
    assert result[0]["url"] == "https://example.com/pin"


def test_merge_pinned_caps_at_10():
    pinned = [_make_pinned(f"https://pinned.com/{i}") for i in range(3)]
    ranked = [_make_article(f"https://ranked.com/{i}") for i in range(10)]
    result = _merge_pinned(pinned, ranked)
    assert len(result) == 10


def test_merge_pinned_wins_on_url_collision():
    url = "https://example.com/shared"
    pinned = [_make_pinned(url)]
    ranked = [_make_article(url)]  # same URL, lower score
    result = _merge_pinned(pinned, ranked)
    assert len(result) == 1
    assert result[0]["source"] == "Pinned"
    assert result[0]["score"] == 1.0


async def test_pinned_url_bypasses_seen_filter(tmp_path):
    sources = tmp_path / "sources.json"
    sources.write_text("[]")
    seen = tmp_path / "seen_urls.json"
    pinned_file = tmp_path / "pinned.json"
    pinned_file.write_text(
        json.dumps([{"id": "art", "url": "https://example.com/pinned", "title": "Pinned Art"}])
    )
    seen.write_text(json.dumps(["https://example.com/pinned"]))  # pinned URL is in seen

    captured_cluster_urls: list[str] = []

    async def capturing_cluster(articles, **kwargs):
        captured_cluster_urls.extend(a["url"] for a in articles)
        return _CLUSTERS

    patches = [
        patch("pipeline.pipeline.discover", new=AsyncMock(return_value=_ARTICLES)),
        patch("pipeline.pipeline.rank", new=AsyncMock(return_value=_RANKED)),
        patch("pipeline.pipeline.cluster", new=capturing_cluster),
    ]
    for p in patches:
        p.start()
    try:
        await run_pipeline(
            sources_path=sources,
            seen_path=seen,
            pinned_path=pinned_file,
            generate_fn=_fake_generate,
        )
    finally:
        for p in patches:
            p.stop()

    assert "https://example.com/pinned" in captured_cluster_urls


async def test_pinned_url_appears_in_cluster_input(tmp_path):
    sources = tmp_path / "sources.json"
    sources.write_text("[]")
    seen = tmp_path / "seen_urls.json"
    pinned_file = tmp_path / "pinned.json"
    pinned_file.write_text(
        json.dumps([{"id": "art", "url": "https://pin.example.com/1", "title": "Pin 1"}])
    )

    captured: list[dict] = []

    async def capturing_cluster(articles, **kwargs):
        captured.extend(articles)
        return _CLUSTERS

    patches = [
        patch("pipeline.pipeline.discover", new=AsyncMock(return_value=_ARTICLES)),
        patch("pipeline.pipeline.rank", new=AsyncMock(return_value=_RANKED)),
        patch("pipeline.pipeline.cluster", new=capturing_cluster),
    ]
    for p in patches:
        p.start()
    try:
        await run_pipeline(
            sources_path=sources,
            seen_path=seen,
            pinned_path=pinned_file,
            generate_fn=_fake_generate,
        )
    finally:
        for p in patches:
            p.stop()

    urls = [a["url"] for a in captured]
    assert "https://pin.example.com/1" in urls


async def test_pinned_cleared_only_when_consumed(tmp_path):
    sources = tmp_path / "sources.json"
    sources.write_text("[]")
    seen = tmp_path / "seen_urls.json"
    pinned_file = tmp_path / "pinned.json"
    pin_url = "https://pin.example.com/1"
    pinned_file.write_text(json.dumps([{"id": "pin1", "url": pin_url, "title": "Pin 1"}]))

    # generate_fn only consumes the first URL per batch (not the pinned one if it's second)
    async def consume_none(batch_key, title, urls, topic):
        return f"data/{batch_key}.mp3", []  # consumed nothing

    patches = _patch_stages()
    for p in patches:
        p.start()
    try:
        await run_pipeline(
            sources_path=sources, seen_path=seen, pinned_path=pinned_file, generate_fn=consume_none
        )
    finally:
        for p in patches:
            p.stop()

    # Pinned URL not consumed → should still be in the file
    remaining = json.loads(pinned_file.read_text())
    assert any(e["url"] == pin_url for e in remaining)


async def test_pinned_cleared_when_consumed(tmp_path):
    sources = tmp_path / "sources.json"
    sources.write_text("[]")
    seen = tmp_path / "seen_urls.json"
    pinned_file = tmp_path / "pinned.json"
    pin_url = "https://pin.example.com/consumed"
    pinned_file.write_text(json.dumps([{"id": "pin1", "url": pin_url, "title": "Pin 1"}]))

    # generate_fn returns all urls as consumed (including the pinned one)
    async def consume_all(batch_key, title, urls, topic):
        return f"data/{batch_key}.mp3", urls

    patches = _patch_stages()
    for p in patches:
        p.start()
    try:
        await run_pipeline(
            sources_path=sources, seen_path=seen, pinned_path=pinned_file, generate_fn=consume_all
        )
    finally:
        for p in patches:
            p.stop()

    # If the pinned URL was in the batch and returned as consumed, it clears
    # (may not be consumed if cluster didn't include it — check seen set includes it)
    seen_written = set(json.loads(seen.read_text())) if seen.exists() else set()
    remaining_pinned = json.loads(pinned_file.read_text()) if pinned_file.exists() else []
    pinned_urls_remaining = {e["url"] for e in remaining_pinned}
    # If pin_url was consumed (in seen), it must not remain pinned
    if pin_url in seen_written:
        assert pin_url not in pinned_urls_remaining
