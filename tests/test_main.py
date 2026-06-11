from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from pipeline.main import app

_PIPELINE_RESULT = {
    "status": "success",
    "batches": [{"title": "Streaming", "mp3": "data/batch_a.mp3"}],
    "articles_seen": 3,
}

_FAILED_RESULT = {
    "status": "failed",
    "batches": [],
    "articles_seen": 0,
}


@pytest.fixture
def client():
    return TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_pipeline_run_returns_200_with_shape(client):
    with patch(
        "pipeline.main.run_pipeline",
        new=AsyncMock(return_value=_PIPELINE_RESULT),
    ):
        r = client.post("/pipeline/run")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"
    assert body["batches"][0]["title"] == "Streaming"
    assert body["batches"][0]["mp3"] == "data/batch_a.mp3"


def test_pipeline_run_returns_500_on_total_failure(client):
    with patch(
        "pipeline.main.run_pipeline",
        new=AsyncMock(return_value=_FAILED_RESULT),
    ):
        r = client.post("/pipeline/run")
    assert r.status_code == 500


def test_auth_status_returns_200_with_status(client):
    with patch(
        "pipeline.main.get_auth_status",
        return_value={"status": "ok", "checked_at": "2026-06-10T06:00:00Z"},
    ):
        r = client.get("/auth/status")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_auth_refresh_returns_200_with_status(client):
    with patch(
        "pipeline.main.refresh_auth",
        new=AsyncMock(return_value={"status": "ok"}),
    ):
        r = client.post("/auth/refresh")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_auth_reauth_returns_200_with_vnc_url(client):
    with patch(
        "pipeline.main.start_reauth",
        new=AsyncMock(
            return_value={"status": "started", "vnc_url": "http://localhost:6080/vnc.html"}
        ),
    ):
        r = client.post("/auth/reauth")
    assert r.status_code == 200
    assert r.json()["vnc_url"] == "http://localhost:6080/vnc.html"
