import asyncio
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path

try:
    from notebooklm import NotebookLM
except ImportError:  # pragma: no cover - real package only present in the container
    NotebookLM = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_POLL_INTERVAL_S = 30
_TIMEOUT_S = 15 * 60
_MAX_ATTEMPTS = 2


def _episodes_dir() -> Path:
    return Path(os.environ.get("EPISODES_DIR", "/app/episodes"))


async def _wait_for_audio(notebook, audio) -> None:
    """Poll the notebook's audio overview until it is ready or the timeout elapses."""
    start = time.monotonic()
    while True:
        status = await notebook.get_audio_status(audio)
        if status == "complete":
            return
        if status == "failed":
            raise RuntimeError("NotebookLM reported audio generation failed")
        if time.monotonic() - start >= _TIMEOUT_S:
            raise TimeoutError(f"Audio generation timed out after {_TIMEOUT_S}s")
        await asyncio.sleep(_POLL_INTERVAL_S)


async def _generate_once(title: str, urls: list[str], dest: Path) -> str:
    nlm = NotebookLM()
    notebook = await nlm.create_notebook(name=f"DE Daily - {title}")
    try:
        for url in urls:
            await notebook.add_source(url)
        audio = await notebook.create_audio_overview(
            focus=f"Practical data engineering techniques. Topic: {title}"
        )
        await _wait_for_audio(notebook, audio)
        await notebook.download_audio(audio, str(dest))
        return str(dest)
    finally:
        await notebook.delete()


async def generate_episode(batch_key: str, title: str, urls: list[str]) -> str:
    """Create an ephemeral NotebookLM notebook, generate the audio overview,
    download it to EPISODES_DIR, and delete the notebook. Returns the MP3 path."""
    today_utc = datetime.now(UTC).strftime("%Y-%m-%d")
    dest = _episodes_dir() / f"{batch_key}-{today_utc}.mp3"
    dest.parent.mkdir(parents=True, exist_ok=True)

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return await _generate_once(title, urls, dest)
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
