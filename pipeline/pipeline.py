import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pipeline.clustering import cluster
from pipeline.discovery import discover
from pipeline.ranking import rank

logger = logging.getLogger(__name__)

_DEFAULT_SOURCES = Path("data/sources.json")
_DEFAULT_SEEN = Path("data/seen_urls.json")

GenerateFn = Callable[[str, str, list[str]], Awaitable[str]]


def _load_seen(seen_path: Path) -> set[str]:
    if not seen_path.exists():
        return set()
    return set(json.loads(seen_path.read_text()))


def _save_seen(seen_path: Path, urls: set[str]) -> None:
    seen_path.parent.mkdir(parents=True, exist_ok=True)
    seen_path.write_text(json.dumps(sorted(urls)))


async def run_pipeline(
    *,
    sources_path: Path = _DEFAULT_SOURCES,
    seen_path: Path = _DEFAULT_SEEN,
    generate_fn: GenerateFn | None = None,
) -> dict[str, Any]:
    if generate_fn is None:
        from pipeline.notebooklm_gen import generate_episode

        generate_fn = generate_episode

    seen_urls = _load_seen(seen_path)

    articles = await discover(sources_path)
    articles = [a for a in articles if a["url"] not in seen_urls]

    ranked = await rank(articles)
    clusters = await cluster(ranked)

    # collect URLs from this batch — only persist after all generations succeed
    batch_urls: set[str] = set()
    for batch in clusters.values():
        batch_urls.update(batch["urls"])

    batches = []
    for batch_key, batch in clusters.items():
        try:
            mp3_path = await generate_fn(batch_key, batch["title"], batch["urls"])
            batches.append({"title": batch["title"], "mp3": mp3_path})
        except Exception:
            logger.exception(
                "Episode generation failed for batch %s (%s)", batch_key, batch["title"]
            )

    if batches:
        _save_seen(seen_path, seen_urls | batch_urls)

    return {"batches": batches, "articles_seen": len(batch_urls)}
