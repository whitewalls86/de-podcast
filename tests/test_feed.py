import io
import json

import pytest
from fastapi.testclient import TestClient

import feed.main as feed_module
from feed.main import app

AUTH = {"Authorization": "Bearer test-token"}
client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_episodes(tmp_path, monkeypatch):
    """Point all file I/O at a fresh temp directory for each test."""
    monkeypatch.setattr(feed_module, "EPISODES_DIR", tmp_path)
    monkeypatch.setattr(feed_module, "EPISODES_JSON", tmp_path / "episodes.json")
    monkeypatch.setattr(feed_module, "FEED_XML", tmp_path / "feed.xml")
    tmp_path.mkdir(parents=True, exist_ok=True)


def post_episode(title="Test Episode", filename="test.mp3", data=b"fake mp3"):
    return client.post(
        "/episodes",
        headers=AUTH,
        data={"title": title, "pub_date": "2026-06-10T06:00:00"},
        files={"file": (filename, io.BytesIO(data), "audio/mpeg")},
    )


# --- health ---


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# --- auth ---


def test_post_episode_no_auth():
    r = client.post("/episodes")
    assert r.status_code == 403


def test_post_episode_wrong_token():
    r = client.post(
        "/episodes",
        headers={"Authorization": "Bearer wrong"},
        data={"title": "T", "pub_date": "2026-06-10T06:00:00"},
        files={"file": ("t.mp3", io.BytesIO(b"x"), "audio/mpeg")},
    )
    assert r.status_code == 401


# --- post episode ---


def test_post_episode_returns_url():
    r = post_episode()
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["url"].endswith("test.mp3")


def test_post_episode_saves_file(tmp_path, monkeypatch):
    monkeypatch.setattr(feed_module, "EPISODES_DIR", tmp_path)
    monkeypatch.setattr(feed_module, "EPISODES_JSON", tmp_path / "episodes.json")
    monkeypatch.setattr(feed_module, "FEED_XML", tmp_path / "feed.xml")
    post_episode(filename="ep1.mp3", data=b"audio content")
    assert (tmp_path / "ep1.mp3").read_bytes() == b"audio content"


def test_post_episode_writes_episodes_json(tmp_path, monkeypatch):
    monkeypatch.setattr(feed_module, "EPISODES_DIR", tmp_path)
    monkeypatch.setattr(feed_module, "EPISODES_JSON", tmp_path / "episodes.json")
    monkeypatch.setattr(feed_module, "FEED_XML", tmp_path / "feed.xml")
    post_episode(title="My Episode")
    episodes = json.loads((tmp_path / "episodes.json").read_text())
    assert len(episodes) == 1
    assert episodes[0]["title"] == "My Episode"


# --- feed.xml ---


def test_feed_xml_404_before_any_episode():
    r = client.get("/feed.xml")
    assert r.status_code == 404


def test_feed_xml_contains_episode_title():
    post_episode(title="Kafka Deep Dive")
    r = client.get("/feed.xml")
    assert r.status_code == 200
    assert b"Kafka Deep Dive" in r.content


def test_feed_xml_content_type():
    post_episode()
    r = client.get("/feed.xml")
    assert "rss+xml" in r.headers["content-type"]


# --- episode serving ---


def test_get_episode_404():
    r = client.get("/episodes/nonexistent.mp3")
    assert r.status_code == 404


# --- retention ---


def test_retention_prunes_oldest(tmp_path, monkeypatch):
    monkeypatch.setattr(feed_module, "EPISODES_DIR", tmp_path)
    monkeypatch.setattr(feed_module, "EPISODES_JSON", tmp_path / "episodes.json")
    monkeypatch.setattr(feed_module, "FEED_XML", tmp_path / "feed.xml")
    monkeypatch.setattr(feed_module, "MAX_EPISODES", 2)

    for i in range(3):
        client.post(
            "/episodes",
            headers=AUTH,
            data={"title": f"Episode {i}", "pub_date": "2026-06-10T06:00:00"},
            files={"file": (f"ep{i}.mp3", io.BytesIO(b"x"), "audio/mpeg")},
        )

    episodes = json.loads((tmp_path / "episodes.json").read_text())
    assert len(episodes) == 2
    assert episodes[0]["title"] == "Episode 1"
    assert not (tmp_path / "ep0.mp3").exists()
