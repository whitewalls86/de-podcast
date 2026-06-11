from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pipeline import notebooklm_gen
from pipeline.notebooklm_gen import generate_episode

_URLS = ["http://example.com/a", "http://example.com/b"]


def _make_nlm(**notebook_overrides):
    """Build a mocked NotebookLM() instance and its notebook."""
    notebook = MagicMock()
    notebook.add_source = AsyncMock()
    notebook.create_audio_overview = AsyncMock(return_value=MagicMock(name="audio"))
    notebook.get_audio_status = AsyncMock(return_value="complete")
    notebook.download_audio = AsyncMock()
    notebook.delete = AsyncMock()
    for key, value in notebook_overrides.items():
        setattr(notebook, key, value)

    nlm = MagicMock()
    nlm.create_notebook = AsyncMock(return_value=notebook)
    return nlm, notebook


@pytest.fixture
def episodes_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("EPISODES_DIR", str(tmp_path))
    return tmp_path


async def test_creates_notebook_with_correct_name(episodes_dir):
    nlm, notebook = _make_nlm()
    with patch("pipeline.notebooklm_gen.NotebookLM", return_value=nlm):
        await generate_episode("batch_a", "Streaming", _URLS)

    nlm.create_notebook.assert_awaited_once_with(name="DE Daily - Streaming")


async def test_sources_added_for_each_url(episodes_dir):
    nlm, notebook = _make_nlm()
    with patch("pipeline.notebooklm_gen.NotebookLM", return_value=nlm):
        await generate_episode("batch_a", "Streaming", _URLS)

    assert notebook.add_source.await_count == len(_URLS)
    added = [c.args[0] for c in notebook.add_source.await_args_list]
    assert added == _URLS


async def test_audio_requested_with_correct_focus(episodes_dir):
    nlm, notebook = _make_nlm()
    with patch("pipeline.notebooklm_gen.NotebookLM", return_value=nlm):
        await generate_episode("batch_a", "Streaming", _URLS)

    notebook.create_audio_overview.assert_awaited_once_with(
        focus="Practical data engineering techniques. Topic: Streaming"
    )


async def test_notebook_deleted_after_success(episodes_dir):
    nlm, notebook = _make_nlm()
    with patch("pipeline.notebooklm_gen.NotebookLM", return_value=nlm):
        await generate_episode("batch_a", "Streaming", _URLS)

    notebook.delete.assert_awaited()


async def test_notebook_deleted_when_download_raises(episodes_dir):
    nlm, notebook = _make_nlm(download_audio=AsyncMock(side_effect=RuntimeError("download boom")))
    with patch("pipeline.notebooklm_gen.NotebookLM", return_value=nlm):
        with pytest.raises(RuntimeError, match="download boom"):
            await generate_episode("batch_a", "Streaming", _URLS)

    notebook.delete.assert_awaited()


async def test_timeout_raises_timeout_error(episodes_dir, monkeypatch):
    monkeypatch.setattr(notebooklm_gen, "_TIMEOUT_S", 0)
    nlm, notebook = _make_nlm(get_audio_status=AsyncMock(return_value="running"))
    with patch("pipeline.notebooklm_gen.NotebookLM", return_value=nlm):
        with patch("pipeline.notebooklm_gen.asyncio.sleep", new=AsyncMock()):
            with pytest.raises(TimeoutError):
                await generate_episode("batch_a", "Streaming", _URLS)


async def test_retry_first_attempt_fails_second_succeeds(episodes_dir):
    nlm, notebook = _make_nlm(
        create_audio_overview=AsyncMock(
            side_effect=[RuntimeError("transient"), MagicMock(name="audio")]
        )
    )
    with patch("pipeline.notebooklm_gen.NotebookLM", return_value=nlm):
        result = await generate_episode("batch_a", "Streaming", _URLS)

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    assert result.endswith(f"batch_a-{today}.mp3")
    assert nlm.create_notebook.await_count == 2


async def test_episodes_dir_is_configurable(tmp_path, monkeypatch):
    monkeypatch.setenv("EPISODES_DIR", str(tmp_path))
    nlm, notebook = _make_nlm()
    with patch("pipeline.notebooklm_gen.NotebookLM", return_value=nlm):
        result = await generate_episode("batch_a", "Streaming", _URLS)

    assert result.startswith(str(tmp_path))


async def test_returned_path_includes_batch_key_and_date(episodes_dir):
    nlm, notebook = _make_nlm()
    with patch("pipeline.notebooklm_gen.NotebookLM", return_value=nlm):
        result = await generate_episode("batch_xyz", "Streaming", _URLS)

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    assert result.endswith(f"batch_xyz-{today}.mp3")
