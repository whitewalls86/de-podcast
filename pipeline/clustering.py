import json

from pipeline.dev_client import get_anthropic_client
from pipeline.topic import DEFAULT_TOPIC

_MODEL = "claude-haiku-4-5-20251001"

_SYSTEM_TAIL = """\
 Group the provided articles into
exactly 2 thematic batches.
Each batch needs a concise title and must contain at least one URL.
Every article URL must appear in exactly one batch.
Copy URLs character-for-character from the input — do not modify, correct, or normalize them.

Return ONLY a JSON object with no commentary, no markdown fences:
{"batch_a":{"title":"...","urls":["..."]},"batch_b":{"title":"...","urls":["..."]}}
"""


def build_system(topic: dict) -> str:
    return f"You are a {topic['name']} content curator.{_SYSTEM_TAIL}"


async def cluster(articles: list[dict], *, topic: dict = DEFAULT_TOPIC) -> dict:
    if len(articles) < 2:
        raise ValueError(
            f"cluster() requires at least 2 articles to form two non-empty batches,"
            f" got {len(articles)}"
        )

    items = [{"url": a["url"], "title": a["title"]} for a in articles]
    user_msg = f"Group these articles into 2 batches:\n{json.dumps(items, indent=2)}"

    client = get_anthropic_client()
    response = await client.messages.create(
        model=_MODEL,
        max_tokens=1024,
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
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude returned invalid JSON from clustering: {e}\nRaw: {raw!r}") from e

    if not isinstance(result, dict):
        raise ValueError(
            f"Claude clustering response must be a JSON object,"
            f" got {type(result).__name__}: {raw!r}"
        )

    # Remap any URLs Claude normalized (e.g. _ → -) back to the canonical input URLs.
    # Only remap when the normalized key is unambiguous (maps to exactly one input URL).
    input_urls = {a["url"] for a in articles}
    norm_counts: dict[str, int] = {}
    for u in input_urls:
        key = u.lower().replace("-", "_")
        norm_counts[key] = norm_counts.get(key, 0) + 1
    norm_to_canonical = {
        u.lower().replace("-", "_"): u
        for u in input_urls
        if norm_counts[u.lower().replace("-", "_")] == 1
    }
    for batch in result.values():
        if isinstance(batch, dict) and isinstance(batch.get("urls"), list):
            batch["urls"] = [
                norm_to_canonical.get(u.lower().replace("-", "_"), u) if isinstance(u, str) else u
                for u in batch["urls"]
            ]

    _validate_clusters(result, input_urls)
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
