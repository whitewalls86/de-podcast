from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pipeline.notebooklm_gen import ArtifactInProgressTimeoutError, generate_episode

_URLS = ["http://example.com/a", "http://example.com/b"]
_TOPIC = {
    "short_name": "DE Daily",
    "generation_instructions": "Practical data engineering techniques.",
}


def _make_client():
    """Build a mocked NotebookLMClient and notebook returned by notebooks.create."""
    nb = MagicMock()
    nb.id = "nb-123"

    audio_status = MagicMock()
    audio_status.task_id = "task-123"

    client = MagicMock()
    client.notebooks.create = AsyncMock(return_value=nb)
    client.notebooks.delete = AsyncMock()
    client.sources.add_url = AsyncMock()
    client.artifacts.generate_audio = AsyncMock(return_value=audio_status)
    client.artifacts.wait_for_completion = AsyncMock()
    client.artifacts.download_audio = AsyncMock()
    return client, nb


async def _raise_timeout_after_closing(coro, *args, **kwargs):
    coro.close()
    raise TimeoutError()


@contextmanager
def _patch_client(client):
    cm = AsyncMock()
    cm.__aenter__.return_value = client
    cm.__aexit__.return_value = False
    with patch("pipeline.notebooklm_gen.NotebookLMClient") as MockClient:
        MockClient.from_storage.return_value = cm
        yield MockClient


@pytest.fixture
def episodes_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("EPISODES_DIR", str(tmp_path))
    return tmp_path


async def test_creates_notebook_with_correct_name(episodes_dir):
    client, _ = _make_client()
    with _patch_client(client):
        await generate_episode("batch_a", "Streaming", _URLS, _TOPIC)
    client.notebooks.create.assert_awaited_once_with("DE Daily - Streaming")


async def test_sources_added_for_each_url(episodes_dir):
    client, nb = _make_client()
    with _patch_client(client):
        await generate_episode("batch_a", "Streaming", _URLS, _TOPIC)
    assert client.sources.add_url.await_count == len(_URLS)
    added = [c.args[1] for c in client.sources.add_url.await_args_list]
    assert added == _URLS
    for call in client.sources.add_url.await_args_list:
        assert call.kwargs.get("wait") is True


async def test_audio_requested_with_correct_focus(episodes_dir):
    client, nb = _make_client()
    with _patch_client(client):
        await generate_episode("batch_a", "Streaming", _URLS, _TOPIC)
    client.artifacts.generate_audio.assert_awaited_once_with(
        nb.id,
        instructions="Practical data engineering techniques. Topic: Streaming",
    )


async def test_notebook_deleted_after_success(episodes_dir):
    client, nb = _make_client()
    with _patch_client(client):
        await generate_episode("batch_a", "Streaming", _URLS, _TOPIC)
    client.notebooks.delete.assert_awaited_once_with(nb.id)


async def test_notebook_deleted_when_download_raises(episodes_dir):
    client, nb = _make_client()
    client.artifacts.download_audio = AsyncMock(side_effect=RuntimeError("download boom"))
    with _patch_client(client):
        with pytest.raises(RuntimeError, match="download boom"):
            await generate_episode("batch_a", "Streaming", _URLS, _TOPIC)
    client.notebooks.delete.assert_awaited()


async def test_timeout_raises_timeout_error(episodes_dir):
    client, _ = _make_client()
    with _patch_client(client):
        with patch(
            "pipeline.notebooklm_gen.asyncio.wait_for",
            side_effect=_raise_timeout_after_closing,
        ):
            with pytest.raises(TimeoutError):
                await generate_episode("batch_a", "Streaming", _URLS, _TOPIC)


async def test_artifact_timeout_is_not_retried(episodes_dir):
    # ArtifactInProgressTimeoutError means generation started but timed out —
    # retrying would burn another daily credit, so it should propagate immediately.
    client, _ = _make_client()
    client.artifacts.generate_audio = AsyncMock(side_effect=ArtifactInProgressTimeoutError())
    with _patch_client(client):
        with pytest.raises(ArtifactInProgressTimeoutError):
            await generate_episode("batch_a", "Streaming", _URLS, _TOPIC)
    assert client.notebooks.create.await_count == 1  # no retry


async def test_asyncio_timeout_is_not_retried(episodes_dir):
    # asyncio.TimeoutError from the outer wait_for watchdog should also not retry.
    client, _ = _make_client()
    with _patch_client(client):
        with patch(
            "pipeline.notebooklm_gen.asyncio.wait_for",
            side_effect=_raise_timeout_after_closing,
        ):
            with pytest.raises(TimeoutError):
                await generate_episode("batch_a", "Streaming", _URLS, _TOPIC)
    assert client.notebooks.create.await_count == 1  # no retry


async def test_retry_first_attempt_fails_second_succeeds(episodes_dir):
    client, nb = _make_client()
    second_status = MagicMock()
    second_status.task_id = "task-ok"
    client.artifacts.generate_audio = AsyncMock(
        side_effect=[RuntimeError("transient"), second_status]
    )
    with _patch_client(client):
        mp3_path, consumed = await generate_episode("batch_a", "Streaming", _URLS, _TOPIC)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    assert mp3_path.endswith(f"batch_a-{today}.mp3")
    assert client.notebooks.create.await_count == 2


async def test_episodes_dir_is_configurable(tmp_path, monkeypatch):
    monkeypatch.setenv("EPISODES_DIR", str(tmp_path))
    client, _ = _make_client()
    with _patch_client(client):
        mp3_path, consumed = await generate_episode("batch_a", "Streaming", _URLS, _TOPIC)
    assert mp3_path.startswith(str(tmp_path))


async def test_returned_path_includes_batch_key_and_date(episodes_dir):
    client, _ = _make_client()
    with _patch_client(client):
        mp3_path, consumed = await generate_episode("batch_xyz", "Streaming", _URLS, _TOPIC)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    assert mp3_path.endswith(f"batch_xyz-{today}.mp3")
