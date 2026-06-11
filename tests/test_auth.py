import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from pipeline.auth import get_auth_status, refresh_auth, start_reauth


def _proc(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _iso(days_from_now):
    return (datetime.now(UTC) + timedelta(days=days_from_now)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_get_auth_status_ok():
    out = json.dumps({"valid": True, "expires_at": _iso(30)})
    with patch("pipeline.auth.subprocess.run", return_value=_proc(stdout=out)):
        result = get_auth_status()
    assert result["status"] == "ok"
    assert result["checked_at"]


def test_get_auth_status_expiring_within_seven_days():
    out = json.dumps({"valid": True, "expires_at": _iso(3)})
    with patch("pipeline.auth.subprocess.run", return_value=_proc(stdout=out)):
        result = get_auth_status()
    assert result["status"] == "expiring"


def test_get_auth_status_expired():
    out = json.dumps({"valid": False})
    with patch("pipeline.auth.subprocess.run", return_value=_proc(stdout=out)):
        result = get_auth_status()
    assert result["status"] == "expired"


def test_get_auth_status_error_on_subprocess_failure():
    with patch("pipeline.auth.subprocess.run", side_effect=FileNotFoundError("no cli")):
        result = get_auth_status()
    assert result["status"] == "error"
    assert result["checked_at"]


def test_get_auth_status_error_on_malformed_json():
    with patch("pipeline.auth.subprocess.run", return_value=_proc(stdout="not json")):
        result = get_auth_status()
    assert result["status"] == "error"


async def test_refresh_auth_ok_on_zero_exit():
    with patch("pipeline.auth.subprocess.run", return_value=_proc(returncode=0)):
        result = await refresh_auth()
    assert result == {"status": "ok"}


async def test_refresh_auth_error_on_nonzero_exit():
    with patch("pipeline.auth.subprocess.run", return_value=_proc(returncode=1, stderr="boom")):
        result = await refresh_auth()
    assert result["status"] == "error"
    assert "boom" in result["detail"]


async def test_start_reauth_starts_processes_and_returns_vnc_url():
    with patch("pipeline.auth.subprocess.Popen") as popen:
        result = await start_reauth()
    assert result["status"] == "started"
    assert result["vnc_url"] == "http://localhost:6080/vnc.html"
    # Xvfb, x11vnc, websockify, notebooklm login
    assert popen.call_count == 4


async def test_start_reauth_raises_on_spawn_failure():
    with patch("pipeline.auth.subprocess.Popen", side_effect=OSError("no xvfb")):
        try:
            await start_reauth()
        except RuntimeError as exc:
            assert "re-auth" in str(exc)
        else:
            raise AssertionError("expected RuntimeError")
