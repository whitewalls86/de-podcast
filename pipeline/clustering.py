import json
import os

import anthropic

_MODEL = "claude-haiku-4-5-20251001"

_SYSTEM = """\
You are a data engineering content curator. Group the provided articles into
exactly 2 thematic batches.
Each batch needs a concise title and must contain at least one URL.
Every article URL must appear in exactly one batch.

Return ONLY a JSON object, no commentary:
{
  "batch_a": {"title": "...", "urls": ["...", ...]},
  "batch_b": {"title": "...", "urls": ["...", ...]}
}
"""


async def cluster(articles: list[dict]) -> dict:
    items = [{"url": a["url"], "title": a["title"]} for a in articles]
    user_msg = f"Group these articles into 2 batches:\n{json.dumps(items, indent=2)}"

    client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = await client.messages.create(
        model=_MODEL,
        max_tokens=1024,
        system=_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )

    raw = response.content[0].text
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude returned invalid JSON from clustering: {e}\nRaw: {raw!r}") from e
