import pytest

from pipeline.pinned import add_pinned, clear_consumed, load_pinned, remove_pinned


def test_load_pinned_absent_returns_empty(tmp_path):
    assert load_pinned(tmp_path / "pinned.json") == []


def test_add_pinned_creates_entry(tmp_path):
    p = tmp_path / "pinned.json"
    entry = add_pinned("https://example.com/article", "Great Article", path=p)
    assert entry["url"] == "https://example.com/article"
    assert entry["title"] == "Great Article"
    assert "id" in entry


def test_add_pinned_persists(tmp_path):
    p = tmp_path / "pinned.json"
    add_pinned("https://example.com/1", "Article One", path=p)
    entries = load_pinned(p)
    assert len(entries) == 1
    assert entries[0]["url"] == "https://example.com/1"


def test_add_pinned_strips_whitespace(tmp_path):
    p = tmp_path / "pinned.json"
    entry = add_pinned("  https://example.com/1  ", "  My Title  ", path=p)
    assert entry["url"] == "https://example.com/1"
    assert entry["title"] == "My Title"


def test_add_pinned_empty_title_raises(tmp_path):
    p = tmp_path / "pinned.json"
    with pytest.raises(ValueError, match="title"):
        add_pinned("https://example.com/1", "", path=p)


def test_add_pinned_whitespace_title_raises(tmp_path):
    p = tmp_path / "pinned.json"
    with pytest.raises(ValueError, match="title"):
        add_pinned("https://example.com/1", "   ", path=p)


def test_add_pinned_empty_url_raises(tmp_path):
    p = tmp_path / "pinned.json"
    with pytest.raises(ValueError, match="Invalid URL"):
        add_pinned("", "Title", path=p)


def test_add_pinned_ftp_url_raises(tmp_path):
    p = tmp_path / "pinned.json"
    with pytest.raises(ValueError, match="Invalid URL"):
        add_pinned("ftp://example.com/file", "Title", path=p)


def test_add_pinned_no_netloc_raises(tmp_path):
    p = tmp_path / "pinned.json"
    with pytest.raises(ValueError, match="Invalid URL"):
        add_pinned("https://", "Title", path=p)


def test_add_pinned_non_http_scheme_raises(tmp_path):
    p = tmp_path / "pinned.json"
    with pytest.raises(ValueError, match="Invalid URL"):
        add_pinned("file:///etc/passwd", "Title", path=p)


def test_add_pinned_duplicate_url_returns_existing(tmp_path):
    p = tmp_path / "pinned.json"
    first = add_pinned("https://example.com/1", "Article One", path=p)
    second = add_pinned("https://example.com/1", "Different Title", path=p)
    assert second["id"] == first["id"]
    assert load_pinned(p) == [first]


def test_add_pinned_multiple_entries(tmp_path):
    p = tmp_path / "pinned.json"
    add_pinned("https://example.com/1", "Article One", path=p)
    add_pinned("https://example.com/2", "Article Two", path=p)
    entries = load_pinned(p)
    assert len(entries) == 2


def test_remove_pinned_removes_entry(tmp_path):
    p = tmp_path / "pinned.json"
    entry = add_pinned("https://example.com/1", "Article One", path=p)
    remove_pinned(entry["id"], path=p)
    assert load_pinned(p) == []


def test_remove_pinned_missing_raises_key_error(tmp_path):
    p = tmp_path / "pinned.json"
    with pytest.raises(KeyError):
        remove_pinned("nonexistent", path=p)


def test_remove_pinned_leaves_others_intact(tmp_path):
    p = tmp_path / "pinned.json"
    e1 = add_pinned("https://example.com/1", "Article One", path=p)
    e2 = add_pinned("https://example.com/2", "Article Two", path=p)
    remove_pinned(e1["id"], path=p)
    remaining = load_pinned(p)
    assert len(remaining) == 1
    assert remaining[0]["id"] == e2["id"]


def test_clear_consumed_drops_matching_urls(tmp_path):
    p = tmp_path / "pinned.json"
    add_pinned("https://example.com/1", "Article One", path=p)
    add_pinned("https://example.com/2", "Article Two", path=p)
    clear_consumed({"https://example.com/1"}, path=p)
    remaining = load_pinned(p)
    assert len(remaining) == 1
    assert remaining[0]["url"] == "https://example.com/2"


def test_clear_consumed_leaves_unmatched_intact(tmp_path):
    p = tmp_path / "pinned.json"
    add_pinned("https://example.com/1", "Article One", path=p)
    clear_consumed({"https://example.com/other"}, path=p)
    assert len(load_pinned(p)) == 1


def test_clear_consumed_empty_set_is_noop(tmp_path):
    p = tmp_path / "pinned.json"
    add_pinned("https://example.com/1", "Article One", path=p)
    clear_consumed(set(), path=p)
    assert len(load_pinned(p)) == 1
