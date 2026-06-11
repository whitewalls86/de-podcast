import asyncio
import contextlib
import json
import logging
import os
import subprocess
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

_VNC_URL = "http://localhost:6080/vnc.html"
_LOGIN_TIMEOUT_S = 30 * 60

# Module-level state tracking the active re-auth session.
_reauth_procs: list[subprocess.Popen] | None = None
_reauth_task: asyncio.Task | None = None


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _classify(data: dict) -> str:
    """Map the real CLI JSON envelope to ok / expiring / expired.

    CLI shape: {"status": "ok"|"error", "checks": {...}, "details": {...}}
    "expiring": cookies present but token_fetch failed — session-token rotation;
    headless /auth/refresh may fix it without a full browser re-auth.
    "expired": no auth file, missing cookies, or any other hard failure.
    """
    if data.get("status") == "ok":
        return "ok"
    checks = data.get("checks", {})
    if checks.get("cookies_present") and checks.get("token_fetch") is False:
        return "expiring"
    return "expired"


def get_auth_status() -> dict:
    try:
        proc = subprocess.run(
            ["notebooklm", "auth", "check", "--test", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return {"status": "error", "checked_at": _now_iso()}
    # Parse JSON regardless of exit code — the CLI exits non-zero for failed auth
    # but still emits the full diagnostic envelope needed to classify the state.
    try:
        data = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        return {"status": "error", "checked_at": _now_iso()}
    return {"status": _classify(data), "checked_at": _now_iso()}


async def refresh_auth() -> dict:
    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            ["notebooklm", "auth", "refresh"],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "error", "detail": str(exc)}
    if proc.returncode == 0:
        return {"status": "ok"}
    return {"status": "error", "detail": (proc.stderr or "").strip() or "auth refresh failed"}


def _stop_vnc_stack() -> None:
    """Terminate all VNC re-auth processes and clear session state."""
    global _reauth_procs, _reauth_task
    procs, _reauth_procs = _reauth_procs, None
    _reauth_task = None
    if procs:
        for proc in procs:
            with contextlib.suppress(OSError):
                proc.terminate()


async def _monitor_login(login_proc: subprocess.Popen) -> None:
    """Wait for the login process to exit (or time out), then tear down the VNC stack."""
    try:
        await asyncio.wait_for(
            asyncio.to_thread(login_proc.wait),
            timeout=_LOGIN_TIMEOUT_S,
        )
    except TimeoutError:
        logger.warning(
            "Re-auth login timed out after %ds — shutting down VNC stack", _LOGIN_TIMEOUT_S
        )
    finally:
        _stop_vnc_stack()


async def start_reauth() -> dict:
    """Bring up Xvfb + x11vnc + websockify (noVNC) and kick off a browser login.

    Returns immediately. The VNC stack is torn down automatically when login exits
    or after a 30-minute timeout. Returns {"status": "already_running"} if a
    session is already active — prevents port-binding conflicts on repeated calls.
    """
    global _reauth_procs, _reauth_task

    if _reauth_procs is not None:
        return {"status": "already_running", "vnc_url": _VNC_URL}

    procs: list[subprocess.Popen] = []
    try:
        procs.append(subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1280x720x24"]))
        procs.append(
            subprocess.Popen(["x11vnc", "-display", ":99", "-nopw", "-forever", "-shared"])
        )
        procs.append(
            subprocess.Popen(["websockify", "--web=/usr/share/novnc", "6080", "localhost:5900"])
        )
        login = subprocess.Popen(["notebooklm", "login"], env={**os.environ, "DISPLAY": ":99"})
        procs.append(login)
    except (OSError, subprocess.SubprocessError) as exc:
        for proc in procs:
            with contextlib.suppress(OSError):
                proc.terminate()
        raise RuntimeError(f"Failed to start re-auth session: {exc}") from exc

    _reauth_procs = procs
    _reauth_task = asyncio.create_task(_monitor_login(login))
    return {"status": "started", "vnc_url": _VNC_URL}
