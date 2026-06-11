import io
import json
import xml.etree.ElementTree as ET

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


def test_get_episode_returns_content():
    post_episode(filename="ep.mp3", data=b"real audio bytes")
    r = client.get("/episodes/ep.mp3")
    assert r.status_code == 200
    assert r.content == b"real audio bytes"


def test_get_episode_content_type():
    post_episode(filename="ep.mp3")
    r = client.get("/episodes/ep.mp3")
    assert r.headers["content-type"] == "audio/mpeg"


# --- file type validation ---


def test_non_mp3_filename_rejected():
    r = client.post(
        "/episodes",
        headers=AUTH,
        data={"title": "T", "pub_date": "2026-06-10T06:00:00"},
        files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert r.status_code == 415


def test_wrong_content_type_rejected():
    r = client.post(
        "/episodes",
        headers=AUTH,
        data={"title": "T", "pub_date": "2026-06-10T06:00:00"},
        files={"file": ("ep.mp3", io.BytesIO(b"x"), "application/octet-stream")},
    )
    assert r.status_code == 415


def test_rejected_upload_does_not_write_file():
    client.post(
        "/episodes",
        headers=AUTH,
        data={"title": "T", "pub_date": "2026-06-10T06:00:00"},
        files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert not (feed_module.EPISODES_DIR / "notes.txt").exists()


# --- pub_date validation ---


def test_invalid_pub_date_returns_422():
    r = client.post(
        "/episodes",
        headers=AUTH,
        data={"title": "T", "pub_date": "not-a-date"},
        files={"file": ("ep.mp3", io.BytesIO(b"x"), "audio/mpeg")},
    )
    assert r.status_code == 422


def test_invalid_pub_date_does_not_write_file():
    client.post(
        "/episodes",
        headers=AUTH,
        data={"title": "T", "pub_date": "not-a-date"},
        files={"file": ("orphan.mp3", io.BytesIO(b"x"), "audio/mpeg")},
    )
    assert not (feed_module.EPISODES_DIR / "orphan.mp3").exists()


# --- unsafe filenames ---
# "." and ".." are rejected (422); traversal paths are stripped to basename.


@pytest.mark.parametrize("bad_name", [".", ".."])
def test_dot_filename_rejected(bad_name):
    r = client.post(
        "/episodes",
        headers=AUTH,
        data={"title": "Bad", "pub_date": "2026-06-10T06:00:00"},
        files={"file": (bad_name, io.BytesIO(b"x"), "audio/mpeg")},
    )
    assert r.status_code == 422


# --- path traversal ---
# Traversal attempts are sanitized to basename — the file is accepted but
# written safely inside EPISODES_DIR, never at the traversal target.


def test_path_traversal_sanitized_to_basename():
    r = client.post(
        "/episodes",
        headers=AUTH,
        data={"title": "Evil", "pub_date": "2026-06-10T06:00:00"},
        files={"file": ("../evil.mp3", io.BytesIO(b"x"), "audio/mpeg")},
    )
    assert r.status_code == 200
    assert r.json()["url"].endswith("evil.mp3")
    assert (feed_module.EPISODES_DIR / "evil.mp3").exists()


def test_nested_path_traversal_sanitized_to_basename():
    r = client.post(
        "/episodes",
        headers=AUTH,
        data={"title": "Evil", "pub_date": "2026-06-10T06:00:00"},
        files={"file": ("../../etc/evil.mp3", io.BytesIO(b"x"), "audio/mpeg")},
    )
    assert r.status_code == 200
    assert (feed_module.EPISODES_DIR / "evil.mp3").exists()


# --- duplicate filenames ---


def test_duplicate_filename_replaces_entry():
    post_episode(filename="today.mp3", data=b"v1", title="Version 1")
    post_episode(filename="today.mp3", data=b"v2", title="Version 2")
    episodes = json.loads(feed_module.EPISODES_JSON.read_text())
    assert len(episodes) == 1
    assert episodes[0]["title"] == "Version 2"
    assert feed_module.EPISODES_DIR.joinpath("today.mp3").read_bytes() == b"v2"


def test_duplicate_filename_feed_reflects_updated_title():
    post_episode(filename="today.mp3", title="Old Title")
    post_episode(filename="today.mp3", title="New Title")
    r = client.get("/feed.xml")
    assert b"New Title" in r.content
    assert b"Old Title" not in r.content


def test_duplicate_filename_multiple_reruns_stays_one_entry():
    for i in range(4):
        post_episode(filename="today.mp3", title=f"Run {i}")
    episodes = json.loads(feed_module.EPISODES_JSON.read_text())
    assert len(episodes) == 1
    assert episodes[0]["title"] == "Run 3"


# --- feed XML / iTunes structure ---

ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"


def test_feed_is_valid_rss():
    post_episode(title="Spark Internals", filename="spark.mp3", data=b"audio")
    xml = ET.fromstring(client.get("/feed.xml").content)
    assert xml.tag == "rss"
    assert xml.get("version") == "2.0"
    assert xml.find("channel") is not None


def test_feed_has_itunes_namespace():
    post_episode()
    content = client.get("/feed.xml").content.decode()
    assert "itunes" in content


def test_feed_item_has_enclosure():
    post_episode(filename="spark.mp3", data=b"x" * 100)
    xml = ET.fromstring(client.get("/feed.xml").content)
    enclosure = xml.find("channel/item/enclosure")
    assert enclosure is not None
    assert enclosure.get("type") == "audio/mpeg"
    assert "spark.mp3" in enclosure.get("url", "")


def test_feed_enclosure_length_matches_file_size():
    data = b"x" * 512
    post_episode(filename="sized.mp3", data=data)
    xml = ET.fromstring(client.get("/feed.xml").content)
    enclosure = xml.find("channel/item/enclosure")
    assert int(enclosure.get("length", 0)) == len(data)


def test_feed_item_has_pub_date():
    post_episode()
    xml = ET.fromstring(client.get("/feed.xml").content)
    assert xml.find("channel/item/pubDate") is not None


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


# --- metadata file isolation ---
# episodes.json and feed.xml live in EPISODES_DIR but must not be served
# through the unauthenticated /episodes/{filename} route.


def test_episodes_json_not_served_via_episode_route():
    post_episode()
    r = client.get("/episodes/episodes.json")
    assert r.status_code == 404


def test_feed_xml_not_served_via_episode_route():
    post_episode()
    r = client.get("/episodes/feed.xml")
    assert r.status_code == 404


# --- URL encoding ---


def test_filename_with_spaces_produces_encoded_url():
    r = client.post(
        "/episodes",
        headers=AUTH,
        data={"title": "Spaced Out", "pub_date": "2026-06-10T06:00:00"},
        files={"file": ("my episode.mp3", io.BytesIO(b"x"), "audio/mpeg")},
    )
    assert r.status_code == 200
    assert "%20" in r.json()["url"]
    assert " " not in r.json()["url"]


def test_encoded_url_appears_in_feed_enclosure():
    client.post(
        "/episodes",
        headers=AUTH,
        data={"title": "Spaced", "pub_date": "2026-06-10T06:00:00"},
        files={"file": ("my episode.mp3", io.BytesIO(b"x"), "audio/mpeg")},
    )
    xml = ET.fromstring(client.get("/feed.xml").content)
    enclosure = xml.find("channel/item/enclosure")
    assert "%20" in enclosure.get("url", "")
    assert " " not in enclosure.get("url", "")


# --- vote links ---


def test_post_episode_with_episode_id_appends_vote_links(monkeypatch):
    monkeypatch.setattr(feed_module, "PIPELINE_HOST", "http://pipeline:8001")
    r = client.post(
        "/episodes",
        headers=AUTH,
        data={
            "title": "dbt Testing",
            "pub_date": "2026-06-10T06:00:00",
            "episode_id": "dbt-testing-2026-06-10",
            "tags": "dbt,testing",
        },
        files={"file": ("ep.mp3", io.BytesIO(b"x"), "audio/mpeg")},
    )
    assert r.status_code == 200
    episodes = json.loads(feed_module.EPISODES_JSON.read_text())
    description = episodes[0]["description"]
    assert "http://pipeline:8001/feedback/dbt-testing-2026-06-10" in description
    assert "vote=up" in description
    assert "vote=down" in description


def test_post_episode_without_episode_id_leaves_description_unchanged():
    r = client.post(
        "/episodes",
        headers=AUTH,
        data={
            "title": "No Vote",
            "pub_date": "2026-06-10T06:00:00",
            "description": "Original description",
        },
        files={"file": ("ep.mp3", io.BytesIO(b"x"), "audio/mpeg")},
    )
    assert r.status_code == 200
    episodes = json.loads(feed_module.EPISODES_JSON.read_text())
    assert episodes[0]["description"] == "Original description"
