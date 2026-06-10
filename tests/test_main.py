from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from pipeline.main import app

_PIPELINE_RESULT = {
    "batches": [{"title": "Streaming", "mp3": "data/batch_a.mp3"}],
    "articles_seen": 3,
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
    assert "batches" in body
    assert "articles_seen" in body
    assert body["batches"][0]["title"] == "Streaming"
    assert body["batches"][0]["mp3"] == "data/batch_a.mp3"
