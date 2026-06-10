import os

# Set defaults before any test module imports a service app.
# Real values are overridden per-test via monkeypatch fixtures.
os.environ.setdefault("FEED_TOKEN", "test-token")
os.environ.setdefault("FEED_HOST", "http://localhost:8000")
os.environ.setdefault("FEED_TITLE", "Test Feed")
