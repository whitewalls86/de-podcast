import json

import pytest

from pipeline.topic import DEFAULT_TOPIC, load_topic, save_topic, validate_topic


def _valid_topic(**overrides) -> dict:
    t = dict(DEFAULT_TOPIC)
    t.update(overrides)
    return t


# --- load_topic ---


def test_load_topic_absent_returns_defaults(tmp_path):
    result = load_topic(tmp_path / "topic.json")
    assert result == DEFAULT_TOPIC


def test_load_topic_absent_returns_copy(tmp_path):
    a = load_topic(tmp_path / "topic.json")
    b = load_topic(tmp_path / "topic.json")
    assert a is not b


def test_load_topic_valid_file(tmp_path):
    topic = _valid_topic(name="New Car", short_name="Car Daily")
    p = tmp_path / "topic.json"
    p.write_text(json.dumps(topic))
    result = load_topic(p)
    assert result["name"] == "New Car"
    assert result["short_name"] == "Car Daily"


def test_load_topic_invalid_file_raises(tmp_path):
    p = tmp_path / "topic.json"
    p.write_text(json.dumps({"name": ""}))  # empty name
    with pytest.raises(ValueError, match="'name'"):
        load_topic(p)


# --- validate_topic ---


@pytest.mark.parametrize(
    "field", ["name", "short_name", "feed_title", "hn_query", "generation_instructions"]
)
def test_validate_missing_str_field_raises(field):
    data = _valid_topic()
    del data[field]
    with pytest.raises(ValueError, match=repr(field)):
        validate_topic(data)


@pytest.mark.parametrize(
    "field", ["name", "short_name", "feed_title", "hn_query", "generation_instructions"]
)
def test_validate_empty_str_field_raises(field):
    data = _valid_topic(**{field: ""})
    with pytest.raises(ValueError, match=repr(field)):
        validate_topic(data)


@pytest.mark.parametrize(
    "field", ["name", "short_name", "feed_title", "hn_query", "generation_instructions"]
)
def test_validate_whitespace_only_str_field_raises(field):
    data = _valid_topic(**{field: "   "})
    with pytest.raises(ValueError, match=repr(field)):
        validate_topic(data)


def test_validate_missing_ranking_criteria_raises():
    data = _valid_topic()
    del data["ranking_criteria"]
    with pytest.raises(ValueError, match="'ranking_criteria'"):
        validate_topic(data)


def test_validate_empty_ranking_criteria_list_raises():
    data = _valid_topic(ranking_criteria=[])
    with pytest.raises(ValueError, match="'ranking_criteria'"):
        validate_topic(data)


def test_validate_ranking_criteria_not_list_raises():
    data = _valid_topic(ranking_criteria="just a string")
    with pytest.raises(ValueError, match="'ranking_criteria'"):
        validate_topic(data)


def test_validate_ranking_criteria_non_string_item_raises():
    data = _valid_topic(ranking_criteria=["good criterion", 123])
    with pytest.raises(ValueError, match="'ranking_criteria'"):
        validate_topic(data)


def test_validate_ranking_criteria_blank_item_raises():
    data = _valid_topic(ranking_criteria=["good criterion", ""])
    with pytest.raises(ValueError, match="'ranking_criteria'"):
        validate_topic(data)


def test_validate_ranking_criteria_only_empty_items_raises():
    data = _valid_topic(ranking_criteria=["", "   "])
    with pytest.raises(ValueError, match="'ranking_criteria'"):
        validate_topic(data)


def test_validate_valid_topic_returns_cleaned_dict():
    data = _valid_topic()
    result = validate_topic(data)
    assert result == data
    assert result is not data


# --- save_topic ---


def test_save_topic_round_trips(tmp_path):
    p = tmp_path / "topic.json"
    topic = _valid_topic(name="World Events", hn_query="world news")
    save_topic(topic, path=p)
    loaded = load_topic(p)
    assert loaded["name"] == "World Events"
    assert loaded["hn_query"] == "world news"


def test_save_topic_rejects_invalid(tmp_path):
    p = tmp_path / "topic.json"
    with pytest.raises(ValueError, match="'name'"):
        save_topic(_valid_topic(name=""), path=p)
    assert not p.exists()


def test_save_topic_creates_parent_dirs(tmp_path):
    p = tmp_path / "sub" / "dir" / "topic.json"
    save_topic(_valid_topic(), path=p)
    assert p.exists()


def test_save_topic_writes_indented_json(tmp_path):
    p = tmp_path / "topic.json"
    save_topic(_valid_topic(), path=p)
    raw = p.read_text()
    assert "\n" in raw  # indented, not compact


# --- admin form round-trip for feed_title ---


def test_feed_title_survives_save_and_load(tmp_path):
    p = tmp_path / "topic.json"
    save_topic(_valid_topic(feed_title="Car Daily"), path=p)
    result = load_topic(p)
    assert result["feed_title"] == "Car Daily"
