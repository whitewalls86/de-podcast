import json

import pytest
from fastapi.testclient import TestClient

from pipeline.main import app
from pipeline.sources import add_source


@pytest.fixture
def admin_paths(tmp_path):
    prev_sources = getattr(app.state, "sources_path", None)
    prev_last_run = getattr(app.state, "last_run_path", None)
    prev_feedback = getattr(app.state, "feedback_path", None)
    prev_seen_urls = getattr(app.state, "seen_urls_path", None)
    prev_topic = getattr(app.state, "topic_path", None)
    prev_pinned = getattr(app.state, "pinned_path", None)
    app.state.sources_path = tmp_path / "sources.json"
    app.state.last_run_path = tmp_path / "last_run.json"
    app.state.feedback_path = tmp_path / "feedback.json"
    app.state.seen_urls_path = tmp_path / "seen_urls.json"
    app.state.topic_path = tmp_path / "topic.json"
    app.state.pinned_path = tmp_path / "pinned.json"
    yield tmp_path
    app.state.sources_path = prev_sources
    app.state.last_run_path = prev_last_run
    app.state.feedback_path = prev_feedback
    app.state.seen_urls_path = prev_seen_urls
    app.state.topic_path = prev_topic
    app.state.pinned_path = prev_pinned


@pytest.fixture
def client(admin_paths):
    return TestClient(app)


def test_dashboard_no_last_run(client):
    r = client.get("/admin")
    assert r.status_code == 200
    assert "No runs recorded" in r.text


def test_dashboard_with_last_run(admin_paths):
    (admin_paths / "last_run.json").write_text(
        json.dumps(
            {
                "timestamp": "2026-06-10T06:00:00Z",
                "status": "success",
                "batches": ["Streaming", "Batch Processing"],
            }
        )
    )
    r = TestClient(app).get("/admin")
    assert r.status_code == 200
    assert "success" in r.text
    assert "Streaming" in r.text
    assert "Batch Processing" in r.text


def test_sources_page_empty(client):
    r = client.get("/admin/sources")
    assert r.status_code == 200
    assert "No sources configured" in r.text


def test_sources_page_with_sources(client, admin_paths):
    add_source("My Feed", "https://example.com/rss", "rss", path=admin_paths / "sources.json")
    r = client.get("/admin/sources")
    assert r.status_code == 200
    assert "My Feed" in r.text


def test_add_source(client, admin_paths):
    r = client.post(
        "/admin/sources",
        data={
            "name": "Test Feed",
            "url": "https://test.com/rss",
            "type": "rss",
        },
    )
    assert r.status_code == 200  # followed redirect to /admin/sources
    sources = json.loads((admin_paths / "sources.json").read_text())
    assert len(sources) == 1
    assert sources[0]["name"] == "Test Feed"
    assert sources[0]["active"] is True


def test_toggle_source(client, admin_paths):
    s = add_source("Feed", "https://example.com/rss", "rss", path=admin_paths / "sources.json")
    r = client.patch(f"/admin/sources/{s['id']}")
    assert r.status_code == 200
    assert r.json()["active"] is False
    r2 = client.patch(f"/admin/sources/{s['id']}")
    assert r2.json()["active"] is True


def test_delete_source(client, admin_paths):
    s = add_source("Feed", "https://example.com/rss", "rss", path=admin_paths / "sources.json")
    r = client.delete(f"/admin/sources/{s['id']}")
    assert r.status_code == 204
    assert (
        not (admin_paths / "sources.json").exists()
        or json.loads((admin_paths / "sources.json").read_text()) == []
    )


def test_add_source_empty_name_returns_422(client):
    r = client.post(
        "/admin/sources", data={"name": "!!!", "url": "https://x.com/rss", "type": "rss"}
    )
    assert r.status_code == 422


def test_add_source_invalid_type_returns_422(client):
    r = client.post(
        "/admin/sources", data={"name": "Feed", "url": "https://x.com/rss", "type": "atom"}
    )
    assert r.status_code == 422


def test_delete_source_missing_returns_404(client):
    r = client.delete("/admin/sources/nonexistent")
    assert r.status_code == 404


def test_toggle_source_missing_returns_404(client):
    r = client.patch("/admin/sources/nonexistent")
    assert r.status_code == 404


def test_clear_seen_urls_empties_file(client, admin_paths):
    (admin_paths / "seen_urls.json").write_text('["https://example.com/1","https://example.com/2"]')
    r = client.delete("/admin/seen-urls")
    assert r.status_code == 204
    assert (admin_paths / "seen_urls.json").read_text() == "[]"


def test_clear_seen_urls_when_file_missing_still_204(client, admin_paths):
    assert not (admin_paths / "seen_urls.json").exists()
    r = client.delete("/admin/seen-urls")
    assert r.status_code == 204
    assert (admin_paths / "seen_urls.json").read_text() == "[]"


def test_clear_seen_urls_when_parent_dir_missing_still_204(admin_paths):
    app.state.seen_urls_path = admin_paths / "data" / "seen_urls.json"
    try:
        r = TestClient(app).delete("/admin/seen-urls")
        assert r.status_code == 204
        assert (admin_paths / "data" / "seen_urls.json").read_text() == "[]"
    finally:
        app.state.seen_urls_path = admin_paths / "seen_urls.json"


def test_feedback_page_no_file_renders_cleanly(client):
    r = client.get("/admin/feedback")
    assert r.status_code == 200
    assert "👍 0" in r.text
    assert "👎 0" in r.text


# --- topic page ---

from pipeline.topic import DEFAULT_TOPIC  # noqa: E402


def test_topic_page_shows_defaults_when_no_file(client):
    r = client.get("/admin/topic")
    assert r.status_code == 200
    assert "Data Engineering" in r.text


def test_topic_page_shows_saved_topic(client, admin_paths):
    import json

    topic = dict(DEFAULT_TOPIC)
    topic["name"] = "New Car"
    (admin_paths / "topic.json").write_text(json.dumps(topic))
    r = client.get("/admin/topic")
    assert r.status_code == 200
    assert "New Car" in r.text


def test_topic_page_post_saves_and_redirects(client, admin_paths):
    r = client.post(
        "/admin/topic",
        data={
            "name": "World Events",
            "short_name": "WE Daily",
            "feed_title": "WE Daily",
            "hn_query": "world news",
            "ranking_criteria": "Breaking news\nImpact",
            "generation_instructions": "Focus on world events.",
        },
    )
    assert r.status_code == 200  # followed redirect to /admin/topic
    import json

    saved = json.loads((admin_paths / "topic.json").read_text())
    assert saved["name"] == "World Events"
    assert saved["ranking_criteria"] == ["Breaking news", "Impact"]


def test_topic_page_post_empty_name_returns_422(client):
    r = client.post(
        "/admin/topic",
        data={
            "name": "",
            "short_name": "WE Daily",
            "feed_title": "WE Daily",
            "hn_query": "world news",
            "ranking_criteria": "Breaking news",
            "generation_instructions": "Focus on events.",
        },
    )
    assert r.status_code == 422


def test_topic_page_post_empty_criteria_returns_422(client):
    r = client.post(
        "/admin/topic",
        data={
            "name": "Events",
            "short_name": "EV",
            "feed_title": "EV Daily",
            "hn_query": "events",
            "ranking_criteria": "   \n   ",  # only whitespace lines
            "generation_instructions": "Focus.",
        },
    )
    assert r.status_code == 422


def test_topic_page_feed_title_round_trips(client, admin_paths):
    r = client.post(
        "/admin/topic",
        data={
            "name": "Cars",
            "short_name": "Car Daily",
            "feed_title": "Car Daily Feed",
            "hn_query": "cars",
            "ranking_criteria": "Safety",
            "generation_instructions": "Car news.",
        },
    )
    assert r.status_code == 200
    r2 = client.get("/admin/topic")
    assert "Car Daily Feed" in r2.text


def test_feedback_page_with_entries_shows_counts_and_tags(admin_paths):
    feedback = admin_paths / "feedback.json"
    entries = [
        {
            "episode_id": "ep-1",
            "title": "dbt Best Practices",
            "topic_tags": ["dbt", "testing"],
            "article_urls": [],
            "vote": "up",
            "timestamp": "2026-06-10T08:00:00Z",
        },
        {
            "episode_id": "ep-2",
            "title": "SQL Basics",
            "topic_tags": ["sql"],
            "article_urls": [],
            "vote": "down",
            "timestamp": "2026-06-10T09:00:00Z",
        },
    ]
    feedback.write_text(json.dumps(entries))
    r = TestClient(app).get("/admin/feedback")
    assert r.status_code == 200
    assert "👍 1" in r.text
    assert "👎 1" in r.text
    assert "dbt" in r.text
    assert "sql" in r.text


# --- pinned URLs ---


def test_sources_page_shows_pinned_section(client):
    r = client.get("/admin/sources")
    assert r.status_code == 200
    assert "Pinned URLs" in r.text


def test_add_pinned_redirects_to_sources(client, admin_paths):
    r = client.post(
        "/admin/pinned",
        data={"url": "https://example.com/article", "title": "Great Article"},
    )
    assert r.status_code == 200  # followed redirect to /admin/sources
    assert "Great Article" in r.text


def test_add_pinned_appears_in_sources_page(client, admin_paths):
    client.post("/admin/pinned", data={"url": "https://example.com/art", "title": "My Pin"})
    r = client.get("/admin/sources")
    assert "My Pin" in r.text


def test_add_pinned_empty_url_returns_422(client):
    r = client.post("/admin/pinned", data={"url": "", "title": "Title"})
    assert r.status_code == 422


def test_add_pinned_empty_title_returns_422(client):
    r = client.post("/admin/pinned", data={"url": "https://example.com/1", "title": ""})
    assert r.status_code == 422


def test_add_pinned_invalid_url_returns_422(client):
    r = client.post("/admin/pinned", data={"url": "ftp://example.com/file", "title": "Title"})
    assert r.status_code == 422


def test_delete_pinned_returns_204(client, admin_paths):
    from pipeline.pinned import add_pinned

    e = add_pinned("https://example.com/1", "Art 1", path=admin_paths / "pinned.json")
    r = client.delete(f"/admin/pinned/{e['id']}")
    assert r.status_code == 204


def test_delete_pinned_missing_returns_404(client):
    r = client.delete("/admin/pinned/nonexistent")
    assert r.status_code == 404


def test_duplicate_pinned_url_is_noop(client, admin_paths):
    client.post("/admin/pinned", data={"url": "https://example.com/1", "title": "Art 1"})
    r = client.post("/admin/pinned", data={"url": "https://example.com/1", "title": "Duplicate"})
    assert r.status_code == 200
    import json

    entries = json.loads((admin_paths / "pinned.json").read_text())
    assert len(entries) == 1
