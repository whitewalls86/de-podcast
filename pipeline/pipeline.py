import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pipeline.clustering import cluster
from pipeline.discovery import discover
from pipeline.ranking import rank

logger = logging.getLogger(__name__)

_DEFAULT_SOURCES = Path("sources.json")
_DEFAULT_SEEN = Path("data/seen_urls.json")
_DEFAULT_LAST_RUN = Path("data/last_run.json")

GenerateFn = Callable[[str, str, list[str]], Awaitable[str]]


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
    generate_fn: GenerateFn | None = None,
) -> dict[str, Any]:
    if generate_fn is None:
        from pipeline.notebooklm_gen import generate_episode

        generate_fn = generate_episode

    seen_urls = _load_seen(seen_path)

    articles = await discover(sources_path)
    articles = [a for a in articles if a["url"] not in seen_urls]

    ranked = await rank(articles)

    if len(ranked) < 2:
        logger.info("Only %d ranked article(s) after dedup — skipping clustering", len(ranked))
        result = {"status": "noop", "batches": [], "articles_seen": 0}
        _write_last_run(last_run_path, result)
        return result

    clusters = await cluster(ranked)

    batches = []
    seen_to_add: set[str] = set()
    for batch_key, batch in clusters.items():
        try:
            mp3_path = await generate_fn(batch_key, batch["title"], batch["urls"])
            batches.append({"title": batch["title"], "mp3": mp3_path})
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
