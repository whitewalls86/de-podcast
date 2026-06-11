import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pipeline.auth import get_auth_status, refresh_auth, start_reauth


def _proc(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _checks(**overrides):
    """Build a checks dict matching the real notebooklm auth check --test --json shape."""
    base = {
        "storage_exists": True,
        "json_valid": True,
        "cookies_present": True,
        "sid_cookie": True,
        "token_fetch": True,
    }
    return {**base, **overrides}


# ── get_auth_status ──────────────────────────────────────────────────────────


def test_get_auth_status_ok():
    out = json.dumps({"status": "ok", "checks": _checks(), "details": {}})
    with patch("pipeline.auth.subprocess.run", return_value=_proc(stdout=out)):
        result = get_auth_status()
    assert result["status"] == "ok"
    assert result["checked_at"]


def test_get_auth_status_expiring_when_cookies_present_but_token_fetch_failed():
    # Real CLI exits non-zero but still emits full diagnostic JSON; must be parsed.
    out = json.dumps({"status": "error", "checks": _checks(token_fetch=False), "details": {}})
    with patch("pipeline.auth.subprocess.run", return_value=_proc(returncode=1, stdout=out)):
        result = get_auth_status()
    assert result["status"] == "expiring"


def test_get_auth_status_expired_when_cookies_missing():
    out = json.dumps(
        {
            "status": "error",
            "checks": _checks(cookies_present=False, token_fetch=None),
            "details": {},
        }
    )
    with patch("pipeline.auth.subprocess.run", return_value=_proc(returncode=1, stdout=out)):
        result = get_auth_status()
    assert result["status"] == "expired"


def test_get_auth_status_parses_json_on_nonzero_exit():
    """Non-zero exit with valid JSON yields a classified state, not a generic error."""
    out = json.dumps({"status": "error", "checks": _checks(cookies_present=False), "details": {}})
    with patch("pipeline.auth.subprocess.run", return_value=_proc(returncode=1, stdout=out)):
        result = get_auth_status()
    assert result["status"] == "expired"  # classified, not "error"


def test_get_auth_status_error_on_subprocess_failure():
    with patch("pipeline.auth.subprocess.run", side_effect=FileNotFoundError("no cli")):
        result = get_auth_status()
    assert result["status"] == "error"
    assert result["checked_at"]


def test_get_auth_status_error_on_malformed_json():
    with patch("pipeline.auth.subprocess.run", return_value=_proc(stdout="not json")):
        result = get_auth_status()
    assert result["status"] == "error"


# ── refresh_auth ─────────────────────────────────────────────────────────────


async def test_refresh_auth_ok_on_zero_exit():
    with patch("pipeline.auth.subprocess.run", return_value=_proc(returncode=0)):
        result = await refresh_auth()
    assert result == {"status": "ok"}


async def test_refresh_auth_error_on_nonzero_exit():
    with patch("pipeline.auth.subprocess.run", return_value=_proc(returncode=1, stderr="boom")):
        result = await refresh_auth()
    assert result["status"] == "error"
    assert "boom" in result["detail"]


# ── start_reauth ─────────────────────────────────────────────────────────────


async def test_start_reauth_starts_processes_and_returns_vnc_url(monkeypatch):
    import pipeline.auth as auth_module

    monkeypatch.setattr(auth_module, "_reauth_procs", None)
    monkeypatch.setattr(auth_module, "_reauth_task", None)
    with patch("pipeline.auth.subprocess.Popen") as popen:
        with patch("pipeline.auth.asyncio.create_task", side_effect=lambda coro: coro.close()):
            result = await start_reauth()
    assert result["status"] == "started"
    assert result["vnc_url"] == "http://localhost:6080/vnc.html"
    # Xvfb, x11vnc, websockify, notebooklm login
    assert popen.call_count == 4


async def test_start_reauth_returns_already_running_when_session_active(monkeypatch):
    import pipeline.auth as auth_module

    monkeypatch.setattr(auth_module, "_reauth_procs", [MagicMock()])
    with patch("pipeline.auth.subprocess.Popen") as popen:
        result = await start_reauth()
    assert result["status"] == "already_running"
    assert result["vnc_url"] == "http://localhost:6080/vnc.html"
    popen.assert_not_called()


async def test_start_reauth_raises_on_spawn_failure(monkeypatch):
    import pipeline.auth as auth_module

    monkeypatch.setattr(auth_module, "_reauth_procs", None)
    with patch("pipeline.auth.subprocess.Popen", side_effect=OSError("no xvfb")):
        with pytest.raises(RuntimeError, match="re-auth"):
            await start_reauth()


async def test_start_reauth_terminates_started_procs_on_partial_failure(monkeypatch):
    """If the 4th Popen fails, the 3 already-started processes are terminated."""
    import pipeline.auth as auth_module

    monkeypatch.setattr(auth_module, "_reauth_procs", None)
    good_procs = [MagicMock() for _ in range(3)]
    call_count = 0

    def popen_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 3:
            return good_procs[call_count - 1]
        raise OSError("login failed to spawn")

    with patch("pipeline.auth.subprocess.Popen", side_effect=popen_side_effect):
        with pytest.raises(RuntimeError):
            await start_reauth()

    for p in good_procs:
        p.terminate.assert_called_once()


# ── VNC lifecycle ─────────────────────────────────────────────────────────────


def test_stop_vnc_stack_terminates_all_procs(monkeypatch):
    import pipeline.auth as auth_module

    mock_procs = [MagicMock() for _ in range(4)]
    monkeypatch.setattr(auth_module, "_reauth_procs", mock_procs)
    auth_module._stop_vnc_stack()
    assert auth_module._reauth_procs is None
    for p in mock_procs:
        p.terminate.assert_called_once()


async def test_login_exit_triggers_vnc_shutdown(monkeypatch):
    import pipeline.auth as auth_module

    mock_procs = [MagicMock() for _ in range(4)]
    monkeypatch.setattr(auth_module, "_reauth_procs", mock_procs)
    login_proc = MagicMock()
    with patch("pipeline.auth.asyncio.to_thread", new=AsyncMock(return_value=None)):
        await auth_module._monitor_login(login_proc)
    assert auth_module._reauth_procs is None
    for p in mock_procs:
        p.terminate.assert_called_once()
