import json

from pipeline.feedback import build_few_shot_context, load_feedback, record_vote


def _entry(episode_id: str, vote: str, title: str = "", tags: list[str] | None = None):
    return {
        "episode_id": episode_id,
        "title": title or episode_id,
        "topic_tags": tags or [],
        "article_urls": [],
        "vote": vote,
        "timestamp": "2026-06-10T08:00:00Z",
    }


# --- record_vote ---


def test_record_vote_creates_file_if_absent(tmp_path):
    path = tmp_path / "fb.json"
    record_vote("ep-1", "Title", ["dbt"], [], "up", path=path)
    assert path.exists()
    data = json.loads(path.read_text())
    assert len(data) == 1
    assert data[0]["episode_id"] == "ep-1"


def test_record_vote_appends_new_entries(tmp_path):
    path = tmp_path / "fb.json"
    record_vote("ep-1", "T1", [], [], "up", path=path)
    record_vote("ep-2", "T2", [], [], "down", path=path)
    entries = load_feedback(path=path)
    assert len(entries) == 2
    ids = [e["episode_id"] for e in entries]
    assert "ep-1" in ids
    assert "ep-2" in ids


def test_record_vote_overwrites_existing_episode_id(tmp_path):
    path = tmp_path / "fb.json"
    record_vote("ep-1", "Title", ["dbt"], [], "up", path=path)
    record_vote("ep-1", "Title", ["dbt"], [], "down", path=path)
    entries = load_feedback(path=path)
    assert len(entries) == 1
    assert entries[0]["vote"] == "down"


def test_record_vote_idempotent_same_vote(tmp_path):
    path = tmp_path / "fb.json"
    record_vote("ep-1", "Title", [], [], "up", path=path)
    record_vote("ep-1", "Title", [], [], "up", path=path)
    assert len(load_feedback(path=path)) == 1


# --- load_feedback ---


def test_load_feedback_returns_empty_when_file_absent(tmp_path):
    assert load_feedback(path=tmp_path / "missing.json") == []


def test_load_feedback_returns_empty_on_malformed_json(tmp_path):
    path = tmp_path / "fb.json"
    path.write_text("not json{{{")
    assert load_feedback(path=path) == []


def test_load_feedback_returns_empty_on_non_list_json(tmp_path):
    path = tmp_path / "fb.json"
    path.write_text('{"key": "value"}')
    assert load_feedback(path=path) == []


def test_load_feedback_returns_newest_first(tmp_path):
    path = tmp_path / "fb.json"
    record_vote("ep-old", "Old", [], [], "up", path=path)
    record_vote("ep-new", "New", [], [], "up", path=path)
    entries = load_feedback(path=path)
    assert entries[0]["episode_id"] == "ep-new"
    assert entries[1]["episode_id"] == "ep-old"


# --- build_few_shot_context ---


def test_build_few_shot_context_empty_with_0_entries(tmp_path):
    assert build_few_shot_context(path=tmp_path / "missing.json") == ""


def test_build_few_shot_context_empty_with_1_entry(tmp_path):
    path = tmp_path / "fb.json"
    record_vote("ep-1", "T1", [], [], "up", path=path)
    assert build_few_shot_context(path=path) == ""


def test_build_few_shot_context_empty_with_2_entries(tmp_path):
    path = tmp_path / "fb.json"
    for i in range(2):
        record_vote(f"ep-{i}", f"T{i}", [], [], "up", path=path)
    assert build_few_shot_context(path=path) == ""


def test_build_few_shot_context_nonempty_with_3_entries(tmp_path):
    path = tmp_path / "fb.json"
    for i in range(3):
        record_vote(f"ep-{i}", f"Title {i}", ["dbt"], [], "up", path=path)
    result = build_few_shot_context(path=path)
    assert result != ""


def test_build_few_shot_context_liked_in_correct_section(tmp_path):
    path = tmp_path / "fb.json"
    for i in range(3):
        record_vote(f"ep-{i}", f"Liked Episode {i}", ["dbt"], [], "up", path=path)
    result = build_few_shot_context(path=path)
    assert "Liked:" in result
    assert "Liked Episode" in result


def test_build_few_shot_context_disliked_in_correct_section(tmp_path):
    path = tmp_path / "fb.json"
    for i in range(3):
        record_vote(f"ep-{i}", f"Disliked Episode {i}", ["sql"], [], "down", path=path)
    result = build_few_shot_context(path=path)
    assert "Disliked:" in result
    assert "Disliked Episode" in result


def test_build_few_shot_context_liked_and_disliked_in_separate_sections(tmp_path):
    path = tmp_path / "fb.json"
    record_vote("ep-up-1", "Great Episode", ["dbt"], [], "up", path=path)
    record_vote("ep-up-2", "Nice Episode", ["spark"], [], "up", path=path)
    record_vote("ep-down-1", "Bad Episode", ["sql"], [], "down", path=path)
    result = build_few_shot_context(path=path)
    liked_pos = result.index("Liked:")
    disliked_pos = result.index("Disliked:")
    great_pos = result.index("Great Episode")
    bad_pos = result.index("Bad Episode")
    assert liked_pos < great_pos < disliked_pos < bad_pos


def test_build_few_shot_context_never_raises_on_malformed_file(tmp_path):
    path = tmp_path / "fb.json"
    path.write_text("{{broken")
    assert build_few_shot_context(path=path) == ""


def test_build_few_shot_context_uses_at_most_10_liked(tmp_path):
    path = tmp_path / "fb.json"
    for i in range(15):
        record_vote(f"ep-{i}", f"Title {i}", ["dbt"], [], "up", path=path)
    result = build_few_shot_context(path=path)
    assert result.count("  -") <= 10
