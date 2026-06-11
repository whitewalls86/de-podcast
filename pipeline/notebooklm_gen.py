import asyncio
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

try:
    from notebooklm import NotebookLMClient
    from notebooklm.exceptions import ArtifactInProgressTimeoutError
except ImportError:  # pragma: no cover - real package only present in the container
    NotebookLMClient = None  # type: ignore[assignment]

    class ArtifactInProgressTimeoutError(Exception):  # type: ignore[no-redef]
        pass


logger = logging.getLogger(__name__)

_TIMEOUT_S = 15 * 60
_MAX_ATTEMPTS = 2


def _episodes_dir() -> Path:
    return Path(os.environ.get("EPISODES_DIR", "/app/episodes"))


async def _generate_once(
    title: str, urls: list[str], dest: Path, topic: dict
) -> tuple[str, list[str]]:
    async with NotebookLMClient.from_storage() as client:
        nb = await client.notebooks.create(f"{topic['short_name']} - {title}")
        try:
            consumed: list[str] = []
            for url in urls:
                try:
                    await client.sources.add_url(nb.id, url, wait=True)
                    consumed.append(url)
                except Exception as url_exc:  # noqa: BLE001
                    logger.warning("Skipping unaddable source %s: %s", url, url_exc)
            if not consumed:
                raise RuntimeError("No sources could be added to the notebook")
            status = await client.artifacts.generate_audio(
                nb.id,
                instructions=f"{topic['generation_instructions']} Topic: {title}",
            )
            await asyncio.wait_for(
                client.artifacts.wait_for_completion(nb.id, status.task_id, timeout=_TIMEOUT_S),
                timeout=_TIMEOUT_S + 30,
            )
            await client.artifacts.download_audio(nb.id, str(dest))
            return str(dest), consumed
        finally:
            await client.notebooks.delete(nb.id)


async def generate_episode(
    batch_key: str, title: str, urls: list[str], topic: dict
) -> tuple[str, list[str]]:
    """Create an ephemeral NotebookLM notebook, generate the audio overview,
    download it to EPISODES_DIR, and delete the notebook.
    Returns (mp3_path, consumed_urls) where consumed_urls are those NotebookLM
    successfully added — skipped URLs are not marked seen and will be retried."""
    today_utc = datetime.now(UTC).strftime("%Y-%m-%d")
    dest = _episodes_dir() / f"{batch_key}-{today_utc}.mp3"
    dest.parent.mkdir(parents=True, exist_ok=True)

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return await _generate_once(title, urls, dest, topic)
        except (ArtifactInProgressTimeoutError, TimeoutError):
            raise  # timeout = generation started but took too long; retrying wastes a credit
        except Exception as exc:  # noqa: BLE001 - retried below, re-raised after last attempt
            last_exc = exc
            logger.warning(
                "Episode generation attempt %d/%d failed for %s: %s",
                attempt,
                _MAX_ATTEMPTS,
                batch_key,
                exc,
            )

    assert last_exc is not None
    raise last_exc
