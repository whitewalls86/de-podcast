import json
from pathlib import Path

from pipeline.dev_client import get_anthropic_client
from pipeline.feedback import DEFAULT_FEEDBACK, build_few_shot_context
from pipeline.topic import DEFAULT_TOPIC

_MODEL = "claude-haiku-4-5-20251001"

_SYSTEM_TAIL = """\

Return ONLY a JSON array. No commentary, no markdown fences, no explanation.
Compact format: [{"url":"...","score":0.92,"topic_tags":["dbt","testing"]}, ...]
"""


def build_system(topic: dict) -> str:
    criteria_lines = "\n".join(f"- {c}" for c in topic["ranking_criteria"])
    return (
        f"You are a {topic['name']} content curator."
        f" Score each article from 0.0 to 1.0 based on:\n"
        f"{criteria_lines}"
        f"{_SYSTEM_TAIL}"
    )


def build_ranking_prompt(articles: list[dict], few_shot_context: str) -> str:
    items = [{"url": a["url"], "title": a["title"], "snippet": a["snippet"]} for a in articles]
    article_block = f"Score these articles:\n{json.dumps(items, indent=2)}"
    if few_shot_context:
        return f"{few_shot_context}\n\n{article_block}"
    return article_block


async def rank(
    articles: list[dict],
    *,
    feedback_path: Path = DEFAULT_FEEDBACK,
    topic: dict = DEFAULT_TOPIC,
) -> list[dict]:
    if not articles:
        return []

    few_shot = build_few_shot_context(path=feedback_path)
    user_msg = build_ranking_prompt(articles, few_shot)

    client = get_anthropic_client()
    response = await client.messages.create(
        model=_MODEL,
        max_tokens=4096,
        system=build_system(topic),
        messages=[{"role": "user", "content": user_msg}],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        end = raw.rfind("```")
        if end != -1:
            raw = raw[:end].strip()
    try:
        scores = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude returned invalid JSON from ranking: {e}\nRaw: {raw!r}") from e

    if not isinstance(scores, list):
        raise ValueError(
            f"Claude ranking response must be a JSON array, got {type(scores).__name__}: {raw!r}"
        )
    for i, item in enumerate(scores):
        if not isinstance(item, dict):
            raise ValueError(f"Claude ranking entry {i} is not an object: {item!r}")
        if not isinstance(item.get("url"), str):
            raise ValueError(f"Claude ranking entry {i} missing string 'url': {item!r}")
        score = item.get("score")
        if isinstance(score, bool) or not isinstance(score, int | float) or not 0 <= score <= 1:
            raise ValueError(
                f"Claude ranking entry {i} 'score' must be a float in [0, 1]: {item!r}"
            )
        tags = item.get("topic_tags")
        if tags is not None and (
            not isinstance(tags, list) or not all(isinstance(t, str) for t in tags)
        ):
            raise ValueError(
                f"Claude ranking entry {i} 'topic_tags' must be an array of strings: {item!r}"
            )

    score_map = {item["url"]: item for item in scores}

    ranked = []
    for article in articles:
        entry = score_map.get(article["url"])
        if entry and entry.get("score", 0) >= 0.5:
            ranked.append(
                {
                    **article,
                    "score": entry["score"],
                    "topic_tags": entry.get("topic_tags", []),
                    "reason": entry.get("reason", ""),
                }
            )

    ranked.sort(key=lambda a: a["score"], reverse=True)
    return ranked[:10]
