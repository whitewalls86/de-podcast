import json
import logging
import os
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from pipeline.clustering import cluster
from pipeline.discovery import discover
from pipeline.feedback import DEFAULT_FEEDBACK
from pipeline.ranking import rank

logger = logging.getLogger(__name__)

_DEFAULT_SOURCES = Path("sources.json")
_DEFAULT_SEEN = Path("data/seen_urls.json")
_DEFAULT_LAST_RUN = Path("data/last_run.json")

GenerateFn = Callable[[str, str, list[str]], Awaitable[str]]


async def _post_to_feed(
    *,
    mp3_path: str,
    title: str,
    episode_id: str,
    topic_tags: list[str],
) -> None:
    """POST a generated episode to the feed service as multipart form data.

    Skips silently when FEED_URL is not configured (e.g. in tests). Raises on a
    non-2xx response so the caller can mark the batch failed.
    """
    feed_url = os.environ.get("FEED_URL")
    if not feed_url:
        logger.debug("FEED_URL not set — skipping feed post for %s", episode_id)
        return

    feed_token = os.environ.get("FEED_TOKEN", "")
    pub_date = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(mp3_path, "rb") as fh:
        files = {"file": (Path(mp3_path).name, fh, "audio/mpeg")}
        data = {
            "title": title,
            "pub_date": pub_date,
            "episode_id": episode_id,
            "tags": ",".join(topic_tags),
            "description": "",
        }
        headers = {"Authorization": f"Bearer {feed_token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{feed_url}/episodes", files=files, data=data, headers=headers
            )

    if resp.status_code // 100 != 2:
        logger.error(
            "Feed POST for %s failed with status %s: %s",
            episode_id,
            resp.status_code,
            resp.text,
        )
        resp.raise_for_status()


def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return re.sub(r"-+", "-", text).strip("-")


def _load_seen(seen_path: Path) -> set[str]:
    if not seen_path.exists():
        return set()
    return set(json.loads(seen_path.read_text()))


def _save_seen(seen_path: Path, urls: set[str]) -> None:
    seen_path.parent.mkdir(parents=True, exist_ok=True)
    seen_path.write_text(json.dumps(sorted(urls)))


def _write_last_run(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "status": result["status"],
                "batches": [b["title"] for b in result.get("batches", [])],
            }
        )
    )


async def run_pipeline(
    *,
    sources_path: Path = _DEFAULT_SOURCES,
    seen_path: Path = _DEFAULT_SEEN,
    last_run_path: Path = _DEFAULT_LAST_RUN,
    feedback_path: Path = DEFAULT_FEEDBACK,
    generate_fn: GenerateFn | None = None,
) -> dict[str, Any]:
    if generate_fn is None:
        from pipeline.notebooklm_gen import generate_episode

        generate_fn = generate_episode

    seen_urls = _load_seen(seen_path)

    articles = await discover(sources_path)
    articles = [a for a in articles if a["url"] not in seen_urls]

    ranked = await rank(articles, feedback_path=feedback_path)

    if len(ranked) < 2:
        logger.info("Only %d ranked article(s) after dedup — skipping clustering", len(ranked))
        result = {"status": "noop", "batches": [], "articles_seen": 0}
        _write_last_run(last_run_path, result)
        return result

    clusters = await cluster(ranked)

    max_batches = int(os.environ.get("MAX_BATCHES", "0")) or len(clusters)
    clusters = dict(list(clusters.items())[:max_batches])

    # Build a URL → tags lookup from ranked articles so each batch inherits
    # the union of its constituent articles' topic tags.
    url_tags: dict[str, list[str]] = {a["url"]: a.get("topic_tags", []) for a in ranked}

    today_utc = datetime.now(UTC).strftime("%Y-%m-%d")
    batches = []
    seen_to_add: set[str] = set()
    for batch_key, batch in clusters.items():
        try:
            mp3_path = await generate_fn(batch_key, batch["title"], batch["urls"])
            episode_id = f"{_slugify(batch['title'])}-{today_utc}"
            batch_tags = sorted({t for url in batch["urls"] for t in url_tags.get(url, [])})
            await _post_to_feed(
                mp3_path=mp3_path,
                title=batch["title"],
                episode_id=episode_id,
                topic_tags=batch_tags,
            )
            batches.append({"title": batch["title"], "mp3": mp3_path, "episode_id": episode_id})
            seen_to_add.update(batch["urls"])
        except Exception:
            logger.exception(
                "Episode generation failed for batch %s (%s)", batch_key, batch["title"]
            )

    if seen_to_add:
        _save_seen(seen_path, seen_urls | seen_to_add)

    if not batches:
        status = "failed"
    elif len(batches) < len(clusters):
        status = "partial"
    else:
        status = "success"

    result = {"status": status, "batches": batches, "articles_seen": len(seen_to_add)}
    _write_last_run(last_run_path, result)
    return result
