import copy
import json
from pathlib import Path

DEFAULT_TOPIC: dict = {
    "name": "Data Engineering",
    "short_name": "DE Daily",
    "feed_title": "DE Daily",
    "hn_query": "data engineering",
    "ranking_criteria": [
        "Practical/technical depth (not opinion fluff)",
        "Relevance to Snowflake, dbt, Spark, Databricks, Kafka, pipeline architecture,"
        " data quality, orchestration",
        "Novelty: new releases, new techniques, not rehashed basics",
        "Source credibility",
    ],
    "generation_instructions": "Practical data engineering techniques.",
}

_REQUIRED_STR_FIELDS = ("name", "short_name", "feed_title", "hn_query", "generation_instructions")


def validate_topic(data: dict) -> dict:
    cleaned: dict = {}
    for field in _REQUIRED_STR_FIELDS:
        if field not in data:
            raise ValueError(f"topic.json field {field!r}: missing")
        val = data[field]
        if not isinstance(val, str) or not val.strip():
            raise ValueError(f"topic.json field {field!r}: must be a non-empty string")
        cleaned[field] = val.strip()

    criteria = data.get("ranking_criteria")
    if criteria is None:
        raise ValueError("topic.json field 'ranking_criteria': missing")
    if not isinstance(criteria, list):
        raise ValueError("topic.json field 'ranking_criteria': must be a list of strings")
    if not all(isinstance(c, str) for c in criteria):
        raise ValueError("topic.json field 'ranking_criteria': must be a list of strings")
    if not all(c.strip() for c in criteria):
        raise ValueError(
            "topic.json field 'ranking_criteria': must contain at least one non-empty string"
        )
    stripped = [c.strip() for c in criteria]
    if not stripped:
        raise ValueError(
            "topic.json field 'ranking_criteria': must contain at least one non-empty string"
        )
    cleaned["ranking_criteria"] = stripped

    return cleaned


def load_topic(path: Path = Path("topic.json")) -> dict:
    if not path.exists():
        return copy.deepcopy(DEFAULT_TOPIC)
    data = json.loads(path.read_text())
    return validate_topic(data)


def save_topic(data: dict, *, path: Path) -> None:
    cleaned = validate_topic(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cleaned, indent=2))
