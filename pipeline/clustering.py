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
    if len(articles) < 2:
        raise ValueError(
            f"cluster() requires at least 2 articles to form two non-empty batches,"
            f" got {len(articles)}"
        )

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
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude returned invalid JSON from clustering: {e}\nRaw: {raw!r}") from e

    if not isinstance(result, dict):
        raise ValueError(
            f"Claude clustering response must be a JSON object,"
            f" got {type(result).__name__}: {raw!r}"
        )
    _validate_clusters(result, {a["url"] for a in articles})
    return result


def _validate_clusters(result: dict, input_urls: set[str]) -> None:
    if set(result.keys()) != {"batch_a", "batch_b"}:
        raise ValueError(
            f"Clustering must return exactly batch_a and batch_b, got: {list(result.keys())}"
        )

    returned: list[str] = []
    for key in ("batch_a", "batch_b"):
        batch = result[key]
        if not isinstance(batch, dict):
            raise ValueError(
                f"Clustering batch {key} must be an object, got {type(batch).__name__}"
            )
        title = batch.get("title", "")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"Clustering returned missing or empty title for {key}")
        urls = batch.get("urls", [])
        if not isinstance(urls, list) or not all(isinstance(u, str) for u in urls):
            raise ValueError(f"Clustering batch {key} 'urls' must be a list of strings")
        if not urls:
            raise ValueError(f"Clustering returned empty URL list for {key}")
        returned.extend(urls)

    returned_set = set(returned)
    if len(returned) != len(returned_set):
        dupes = [u for u in returned if returned.count(u) > 1]
        raise ValueError(f"Clustering duplicated URLs across batches: {list(set(dupes))}")
    if returned_set != input_urls:
        missing = input_urls - returned_set
        extra = returned_set - input_urls
        parts = []
        if missing:
            parts.append(f"missing {list(missing)}")
        if extra:
            parts.append(f"unknown {list(extra)}")
        raise ValueError(f"Clustering URL mismatch — {'; '.join(parts)}")
