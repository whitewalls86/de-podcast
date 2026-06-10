import json
import subprocess
from unittest.mock import MagicMock, patch

import anthropic
import pytest

from pipeline.dev_client import DevClient, get_anthropic_client

_CLI_FLAGS = ["claude", "-p", "--output-format", "json"]


def make_envelope(text: str, usage: dict | None = None) -> str:
    return json.dumps({"result": text, "usage": usage or {}})


def make_completed_process(stdout: str = "", returncode: int = 0, stderr: str = ""):
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
async def test_dev_client_returns_result_text(monkeypatch):
    client = DevClient()
    stdout = make_envelope("some output")
    with patch("subprocess.run", return_value=make_completed_process(stdout=stdout)) as mock_run:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            system="sys",
            messages=[{"role": "user", "content": "msg"}],
        )
    assert response.content[0].text == "some output"
    # Verify stdin invocation and correct flags (guards against Windows CreateProcess length limit regression)
    args, kwargs = mock_run.call_args
    assert args[0] == _CLI_FLAGS
    assert kwargs["input"] == "sys\n\nmsg"


@pytest.mark.asyncio
async def test_dev_client_logs_usage(capsys):
    client = DevClient()
    usage = {"input_tokens": 100, "output_tokens": 50, "total_cost_usd": 0.0012}
    stdout = make_envelope("hello", usage=usage)
    with patch("subprocess.run", return_value=make_completed_process(stdout=stdout)):
        await client.messages.create(
            model="m", max_tokens=100, messages=[{"role": "user", "content": "x"}]
        )
    out = capsys.readouterr().out
    assert "input=100" in out
    assert "output=50" in out
    assert "cost=$0.0012" in out


@pytest.mark.asyncio
async def test_dev_client_non_json_stdout_raises():
    client = DevClient()
    with patch("subprocess.run", return_value=make_completed_process(stdout="not json")):
        with pytest.raises(RuntimeError, match="non-JSON output"):
            await client.messages.create(
                model="m", max_tokens=100, messages=[{"role": "user", "content": "x"}]
            )


@pytest.mark.asyncio
async def test_dev_client_missing_result_field_raises():
    client = DevClient()
    with patch(
        "subprocess.run",
        return_value=make_completed_process(stdout=json.dumps({"usage": {}})),
    ):
        with pytest.raises(RuntimeError, match="missing 'result' field"):
            await client.messages.create(
                model="m", max_tokens=100, messages=[{"role": "user", "content": "x"}]
            )


@pytest.mark.asyncio
async def test_dev_client_nonzero_exit_raises():
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
async def test_dev_client_empty_stdout_raises():
    client = DevClient()
    with patch("subprocess.run", return_value=make_completed_process(stdout="   ")):
        with pytest.raises(RuntimeError, match="empty output"):
            await client.messages.create(
                model="m", max_tokens=100, messages=[{"role": "user", "content": "x"}]
            )


@pytest.mark.asyncio
async def test_dev_client_timeout_raises():
    client = DevClient()
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=120)):
        with pytest.raises(RuntimeError, match="timed out"):
            await client.messages.create(
                model="m", max_tokens=100, messages=[{"role": "user", "content": "x"}]
            )


@pytest.mark.asyncio
async def test_dev_client_not_on_path_raises():
    client = DevClient()
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        with pytest.raises(FileNotFoundError, match="claude CLI not found"):
            await client.messages.create(
                model="m", max_tokens=100, messages=[{"role": "user", "content": "x"}]
            )
