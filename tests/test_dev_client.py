import subprocess
from unittest.mock import MagicMock, patch

import anthropic
import pytest

from pipeline.dev_client import DevClient, get_anthropic_client


def make_completed_process(stdout: str = "hello", returncode: int = 0, stderr: str = ""):
    result = MagicMock(spec=subprocess.CompletedProcess)
    result.stdout = stdout
    result.returncode = returncode
    result.stderr = stderr
    return result


def test_get_anthropic_client_returns_async_anthropic_when_unset(monkeypatch):
    monkeypatch.delenv("USE_DEV_CLIENT", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    client = get_anthropic_client()
    assert isinstance(client, anthropic.AsyncAnthropic)


def test_get_anthropic_client_returns_dev_client_when_true(monkeypatch):
    monkeypatch.setenv("USE_DEV_CLIENT", "true")
    client = get_anthropic_client()
    assert isinstance(client, DevClient)


@pytest.mark.asyncio
async def test_dev_client_returns_stdout_as_text(monkeypatch):
    monkeypatch.setenv("USE_DEV_CLIENT", "true")
    client = DevClient()
    with patch(
        "subprocess.run", return_value=make_completed_process(stdout="some output")
    ) as mock_run:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            system="sys",
            messages=[{"role": "user", "content": "msg"}],
        )
    assert response.content[0].text == "some output"
    # Verify the prompt travels via stdin, not as a CLI argument (Windows CreateProcess length limit)
    args, kwargs = mock_run.call_args
    assert args[0] == ["claude", "-p"]
    assert kwargs["input"] == "sys\n\nmsg"


@pytest.mark.asyncio
async def test_dev_client_strips_markdown_fences():
    client = DevClient()
    fenced = "```json\n[1, 2, 3]\n```"
    with patch("subprocess.run", return_value=make_completed_process(stdout=fenced)):
        response = await client.messages.create(
            model="m", max_tokens=100, messages=[{"role": "user", "content": "x"}]
        )
    assert response.content[0].text == "[1, 2, 3]"


@pytest.mark.asyncio
async def test_dev_client_nonzero_exit_raises(monkeypatch):
    client = DevClient()
    with patch(
        "subprocess.run",
        return_value=make_completed_process(stdout="", returncode=1, stderr="oops"),
    ):
        with pytest.raises(RuntimeError, match="exited with code 1"):
            await client.messages.create(
                model="m", max_tokens=100, messages=[{"role": "user", "content": "x"}]
            )


@pytest.mark.asyncio
async def test_dev_client_empty_stdout_raises(monkeypatch):
    client = DevClient()
    with patch("subprocess.run", return_value=make_completed_process(stdout="   ")):
        with pytest.raises(RuntimeError, match="empty output"):
            await client.messages.create(
                model="m", max_tokens=100, messages=[{"role": "user", "content": "x"}]
            )


@pytest.mark.asyncio
async def test_dev_client_timeout_raises(monkeypatch):
    client = DevClient()
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=120)):
        with pytest.raises(RuntimeError, match="timed out"):
            await client.messages.create(
                model="m", max_tokens=100, messages=[{"role": "user", "content": "x"}]
            )


@pytest.mark.asyncio
async def test_dev_client_not_on_path_raises(monkeypatch):
    client = DevClient()
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        with pytest.raises(FileNotFoundError, match="claude CLI not found"):
            await client.messages.create(
                model="m", max_tokens=100, messages=[{"role": "user", "content": "x"}]
            )
