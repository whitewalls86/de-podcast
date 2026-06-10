import json
import os

import anthropic

_MODEL = "claude-haiku-4-5-20251001"

_SYSTEM = """\
You are a data engineering content curator. Score each article from 0.0 to 1.0 based on:
- Practical/technical depth (not opinion fluff)
- Relevance to: Snowflake, dbt, Spark, Databricks, Kafka, pipeline architecture,
  data quality, orchestration
- Novelty: new releases, new techniques, not rehashed basics
- Source credibility

Return ONLY a JSON array, no commentary:
[{"url": "...", "score": 0.92, "reason": "one sentence"}, ...]
"""


async def rank(articles: list[dict]) -> list[dict]:
    if not articles:
        return []

    items = [{"url": a["url"], "title": a["title"], "snippet": a["snippet"]} for a in articles]
    user_msg = f"Score these articles:\n{json.dumps(items, indent=2)}"

    client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = await client.messages.create(
        model=_MODEL,
        max_tokens=2048,
        system=_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )

    raw = response.content[0].text
    try:
        scores = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude returned invalid JSON from ranking: {e}\nRaw: {raw!r}") from e

    score_map = {item["url"]: item for item in scores}

    ranked = []
    for article in articles:
        entry = score_map.get(article["url"])
        if entry and entry.get("score", 0) >= 0.5:
            ranked.append({**article, "score": entry["score"], "reason": entry.get("reason", "")})

    ranked.sort(key=lambda a: a["score"], reverse=True)
    return ranked[:10]
