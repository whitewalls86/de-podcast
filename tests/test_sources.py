import json

import pytest

from pipeline.sources import add_source, list_sources, remove_source, toggle_source


@pytest.fixture
def sources_file(tmp_path):
    f = tmp_path / "sources.json"
    f.write_text(
        json.dumps(
            [
                {
                    "id": "source-a",
                    "name": "Source A",
                    "url": "https://a.com/feed",
                    "type": "rss",
                    "active": True,
                }
            ]
        )
    )
    return f


def test_list_empty(tmp_path):
    assert list_sources(tmp_path / "sources.json") == []


def test_list(sources_file):
    result = list_sources(sources_file)
    assert len(result) == 1
    assert result[0]["name"] == "Source A"
    assert result[0]["id"] == "source-a"


def test_add(tmp_path):
    p = tmp_path / "sources.json"
    s = add_source("My Feed", "https://example.com/rss", "rss", path=p)
    assert s["name"] == "My Feed"
    assert s["url"] == "https://example.com/rss"
    assert s["active"] is True
    assert "id" in s
    assert list_sources(p) == [s]


def test_add_dedup_by_url(tmp_path):
    p = tmp_path / "sources.json"
    s1 = add_source("Feed One", "https://example.com/rss", "rss", path=p)
    s2 = add_source("Feed Two", "https://example.com/rss", "rss", path=p)
    assert s1["id"] == s2["id"]
    assert len(list_sources(p)) == 1


def test_add_id_collision(tmp_path):
    p = tmp_path / "sources.json"
    s1 = add_source("Feed", "https://a.com/rss", "rss", path=p)
    s2 = add_source("Feed", "https://b.com/rss", "rss", path=p)
    assert s1["id"] != s2["id"]
    assert len(list_sources(p)) == 2


def test_remove(sources_file):
    remove_source("source-a", path=sources_file)
    assert list_sources(sources_file) == []


def test_remove_missing_raises(sources_file):
    with pytest.raises(KeyError):
        remove_source("nonexistent", path=sources_file)


def test_toggle(sources_file):
    s = toggle_source("source-a", path=sources_file)
    assert s["active"] is False
    s = toggle_source("source-a", path=sources_file)
    assert s["active"] is True


def test_toggle_missing_raises(sources_file):
    with pytest.raises(KeyError):
        toggle_source("nonexistent", path=sources_file)


def test_add_empty_slug_raises(tmp_path):
    with pytest.raises(ValueError, match="empty slug"):
        add_source("!!!", "https://example.com/rss", "rss", path=tmp_path / "sources.json")


def test_add_whitespace_name_raises(tmp_path):
    with pytest.raises(ValueError, match="empty slug"):
        add_source("   ", "https://example.com/rss", "rss", path=tmp_path / "sources.json")


def test_add_invalid_type_raises(tmp_path):
    with pytest.raises(ValueError, match="Invalid source type"):
        add_source("Feed", "https://example.com/rss", "atom", path=tmp_path / "sources.json")
