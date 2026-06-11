import asyncio
import json
import logging
import os
import subprocess
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

_VNC_URL = "http://localhost:6080/vnc.html"


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
        if proc.returncode != 0:
            return {"status": "error", "checked_at": _now_iso()}
        data = json.loads(proc.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
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


async def start_reauth() -> dict:
    """Bring up Xvfb + x11vnc + websockify (noVNC) and kick off a browser login.

    The login process is fire-and-forget; the VNC stack must stay running so the
    user can complete the login in the browser via the returned URL.
    """
    try:
        subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1280x720x24"])
        subprocess.Popen(["x11vnc", "-display", ":99", "-nopw", "-forever", "-shared"])
        subprocess.Popen(["websockify", "--web=/usr/share/novnc", "6080", "localhost:5900"])
        subprocess.Popen(["notebooklm", "login"], env={**os.environ, "DISPLAY": ":99"})
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"Failed to start re-auth session: {exc}") from exc
    return {"status": "started", "vnc_url": _VNC_URL}
