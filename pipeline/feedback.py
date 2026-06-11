import json
import logging
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_FEEDBACK = Path("data/feedback.json")


def record_vote(
    episode_id: str,
    title: str,
    topic_tags: list[str],
    article_urls: list[str],
    vote: str,
    *,
    path: Path = DEFAULT_FEEDBACK,
) -> None:
    entries = load_feedback(path=path)
    entries = [e for e in entries if e.get("episode_id") != episode_id]
    entries.insert(
        0,
        {
            "episode_id": episode_id,
            "title": title,
            "topic_tags": topic_tags,
            "article_urls": article_urls,
            "vote": vote,
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2))


def load_feedback(*, path: Path = DEFAULT_FEEDBACK) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


def build_few_shot_context(*, path: Path = DEFAULT_FEEDBACK) -> str:
    try:
        entries = load_feedback(path=path)
    except Exception:
        return ""
    if len(entries) < 3:
        return ""
    liked = [e for e in entries if e.get("vote") == "up"][:10]
    disliked = [e for e in entries if e.get("vote") == "down"][:10]
    if not liked and not disliked:
        return ""
    lines = ["User feedback on past episodes:"]
    if liked:
        lines.append("Liked:")
        for e in liked:
            tags = ", ".join(e.get("topic_tags") or [])
            lines.append(f'  - "{e.get("title", "")}" [tags: {tags}]')
    if disliked:
        lines.append("Disliked:")
        for e in disliked:
            tags = ", ".join(e.get("topic_tags") or [])
            lines.append(f'  - "{e.get("title", "")}" [tags: {tags}]')
    return "\n".join(lines)
