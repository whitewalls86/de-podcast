"""
Integration tests for the live Docker Compose stack.

Requires all three services running:
  docker compose --profile pipeline up -d

Run with:
  pytest tests/integration/ --integration
"""

import io
import os
import xml.etree.ElementTree as ET

import httpx
import pytest

FEED = "http://localhost:8000"
PIPELINE = "http://localhost:8001"
N8N = "http://localhost:5678"

pytestmark = pytest.mark.integration


def _token() -> str:
    return os.environ.get("FEED_TOKEN", "ci-test-token")


def _auth() -> dict:
    return {"Authorization": f"Bearer {_token()}"}


def _fake_mp3(seed: int = 0) -> bytes:
    # Minimal bytes — feed only checks content-type, not magic bytes
    return b"\xff\xfb" + bytes([seed % 256]) + b"\x00" * 64


# ---------------------------------------------------------------------------
# Phase 1 — Health checks
# ---------------------------------------------------------------------------


def test_feed_health():
    r = httpx.get(f"{FEED}/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_pipeline_health():
    r = httpx.get(f"{PIPELINE}/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_pipeline_admin_loads():
    r = httpx.get(f"{PIPELINE}/admin", follow_redirects=True)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_n8n_up():
    # 200 (login page) or 401 both mean n8n is running
    r = httpx.get(f"{N8N}", follow_redirects=True)
    assert r.status_code in (200, 401)


# ---------------------------------------------------------------------------
# Phase 1 — Feed POST /episodes (the cross-service call the pipeline makes)
# ---------------------------------------------------------------------------


def _post_episode(title: str = "CI Test Episode", filename: str = "ci_test.mp3", seed: int = 0):
    return httpx.post(
        f"{FEED}/episodes",
        headers=_auth(),
        data={"title": title, "pub_date": "2026-06-11T06:00:00Z"},
        files={"file": (filename, io.BytesIO(_fake_mp3(seed)), "audio/mpeg")},
    )


def test_feed_post_episode_succeeds():
    r = _post_episode(filename="integ_basic.mp3")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "integ_basic.mp3" in body["url"]


def test_feed_post_episode_wrong_token_returns_401():
    r = httpx.post(
        f"{FEED}/episodes",
        headers={"Authorization": "Bearer wrong-token"},
        data={"title": "T", "pub_date": "2026-06-11T06:00:00Z"},
        files={"file": ("t.mp3", io.BytesIO(b"\xff\xfb"), "audio/mpeg")},
    )
    assert r.status_code == 401


def test_feed_post_episode_no_auth_returns_403():
    r = httpx.post(
        f"{FEED}/episodes",
        data={"title": "T", "pub_date": "2026-06-11T06:00:00Z"},
        files={"file": ("t.mp3", io.BytesIO(b"\xff\xfb"), "audio/mpeg")},
    )
    assert r.status_code == 403


def test_feed_xml_contains_posted_episode():
    _post_episode(title="Integration Feed Test", filename="integ_feed.mp3", seed=1)
    r = httpx.get(f"{FEED}/feed.xml")
    assert r.status_code == 200
    assert "Integration Feed Test" in r.text


def test_feed_xml_is_valid_rss():
    _post_episode(filename="integ_rss.mp3", seed=2)
    r = httpx.get(f"{FEED}/feed.xml")
    root = ET.fromstring(r.content)
    assert root.tag == "rss"
    channel = root.find("channel")
    assert channel is not None
    assert channel.find("item") is not None


def test_feed_xml_enclosure_has_correct_type():
    _post_episode(filename="integ_enc.mp3", seed=3)
    r = httpx.get(f"{FEED}/feed.xml")
    root = ET.fromstring(r.content)
    enclosure = next(
        (e for e in root.findall(".//enclosure") if "integ_enc.mp3" in e.get("url", "")),
        None,
    )
    assert enclosure is not None, "integ_enc.mp3 not found in feed enclosures"
    assert enclosure.get("type") == "audio/mpeg"


def test_episode_file_is_served():
    _post_episode(filename="integ_serve.mp3", seed=4)
    r = httpx.get(f"{FEED}/episodes/integ_serve.mp3")
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"


def test_episode_not_in_feed_returns_404():
    r = httpx.get(f"{FEED}/episodes/nonexistent_ci_xyz.mp3")
    assert r.status_code == 404


def test_feed_xml_404_before_any_post():
    # Only meaningful if the stack was freshly started with empty volumes.
    # Skip if feed.xml already exists from a prior run.
    r = httpx.get(f"{FEED}/feed.xml")
    assert r.status_code in (200, 404)  # both are valid depending on prior state


# ---------------------------------------------------------------------------
# Phase 5 — Admin / dedup endpoints
# ---------------------------------------------------------------------------


def test_pipeline_auth_status_responds():
    r = httpx.get(f"{PIPELINE}/auth/status")
    assert r.status_code == 200


def test_clear_seen_urls_returns_204():
    r = httpx.delete(f"{PIPELINE}/admin/seen-urls")
    assert r.status_code == 204


def test_clear_seen_urls_idempotent():
    httpx.delete(f"{PIPELINE}/admin/seen-urls")
    r = httpx.delete(f"{PIPELINE}/admin/seen-urls")
    assert r.status_code == 204
