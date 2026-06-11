import json

import pytest
from fastapi.testclient import TestClient

from pipeline.main import app
from pipeline.sources import add_source


@pytest.fixture
def admin_paths(tmp_path):
    prev_sources = getattr(app.state, "sources_path", None)
    prev_last_run = getattr(app.state, "last_run_path", None)
    app.state.sources_path = tmp_path / "sources.json"
    app.state.last_run_path = tmp_path / "last_run.json"
    yield tmp_path
    app.state.sources_path = prev_sources
    app.state.last_run_path = prev_last_run


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


def test_feedback_page(client):
    r = client.get("/admin/feedback")
    assert r.status_code == 200
    assert "coming" in r.text.lower()
