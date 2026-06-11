# Enhancements Build Plan / Implementation Spec

Two enhancements to the DE Daily Podcast pipeline:

1. **Pin a URL** — force-add a specific URL to the next run, auto-scored, still clustered.
2. **Swappable topic** — reconfigure the podcast subject (e.g. New Car, World Events) via config, not code.

Decisions locked in:

- Pin title is **required in the admin form** (no HTML title fetching).
- Topic config lives in `config/topic.json` and is editable via an `/admin/topic` page.
- **Build topic plumbing first, then pinned URLs.** They are conceptually independent, but
  implementation-wise pinned URLs depend on the article-dict shape and the rank/cluster flow
  that topic plumbing touches. Build against the updated contracts.

---

## Enhancement 2 — Swappable podcast topic (build first)

**Goal:** Hand the project to someone who turns it into a "New Car" or "World Events"
podcast by editing config, not code.

### Hardcoded topic locations (the real blockers)

- `pipeline/ranking.py` `_SYSTEM` — lists DE technologies
- `pipeline/clustering.py` `_SYSTEM` — "data engineering content curator"
- `pipeline/discovery.py` `_HN_BASE_PARAMS` — query `"data engineering"`
- `pipeline/notebooklm_gen.py` — generation instructions + `"DE Daily - {title}"` notebook name
- `config/sources.json` — already data, already swappable

### `config/topic.json` schema

```json
{
  "name": "Data Engineering",
  "short_name": "DE Daily",
  "feed_title": "DE Daily",
  "hn_query": "data engineering",
  "ranking_criteria": [
    "Practical/technical depth (not opinion fluff)",
    "Relevance to Snowflake, dbt, Spark, Databricks, Kafka, pipeline architecture, data quality, orchestration",
    "Novelty: new releases, new techniques, not rehashed basics",
    "Source credibility"
  ],
  "generation_instructions": "Practical data engineering techniques."
}
```

`feed_title` is the **intended** source of truth for the RSS feed title, but the feed
service does not consume it in v1 — see "Feed title gap" below.

`ranking_criteria` is a `list[str]` (not one multiline string): easier admin editing,
cleaner prompt building, easier tests.

**Field rules**

| Field | Type | Required | Default (when file absent) |
|---|---|---|---|
| `name` | `str`, non-empty after strip | yes | `"Data Engineering"` |
| `short_name` | `str`, non-empty after strip | yes | `"DE Daily"` |
| `feed_title` | `str`, non-empty after strip | yes | `"DE Daily"` |
| `hn_query` | `str`, non-empty after strip | yes | `"data engineering"` |
| `ranking_criteria` | `list[str]`, ≥1 non-empty item | yes | the four DE criteria above |
| `generation_instructions` | `str`, non-empty after strip | yes | `"Practical data engineering techniques."` |

- **File absent** → `load_topic` returns the full default dict (existing DE behavior unchanged).
- **File present but partial/malformed** → `load_topic` raises `ValueError` with the offending
  field; the pipeline should not silently run on a half-broken config. (The admin save path
  validates first, so a broken file only happens via manual edit.)
- **Empty strings / empty list** are invalid for required fields — treated as missing.

### `pipeline/topic.py`

- `DEFAULT_TOPIC: dict` — the dict above as a module constant.
- `load_topic(path: Path = Path("topic.json")) -> dict`
  - file absent → `copy of DEFAULT_TOPIC`
  - present → parse JSON, run `validate_topic`, return the validated dict
- `validate_topic(data: dict) -> dict` — enforces the field rules table; raises `ValueError`
  (`f"topic.json field {name!r}: {reason}"`). Strips strings; rejects empty.
- `save_topic(data: dict, *, path: Path) -> None` — validates then writes `indent=2`, `mkdir parents`.

### Prompt builders (replace the two `_SYSTEM` constants)

- `ranking.py`: `build_system(topic: dict) -> str` — renders criteria as a bulleted list:
  ```
  You are a {name} content curator. Score each article from 0.0 to 1.0 based on:
  - {ranking_criteria[0]}
  - {ranking_criteria[1]}
  ...
  Return ONLY a JSON array. ... (unchanged tail)
  ```
  `rank()` gains `topic: dict` param (not a path — see threading decision) and builds the
  system prompt per call.
- `clustering.py`: `build_system(topic: dict) -> str` — "You are a {name} content curator.
  Group the provided articles into exactly 2 thematic batches. ..." (unchanged tail).
  `cluster()` gains `topic: dict` param.

### Threading decision (explicit)

`run_pipeline` loads the topic **once** via `load_topic(topic_path)` and passes the loaded
`dict` down — not the path. This keeps each function pure/testable and avoids repeated disk
reads.

- `run_pipeline(..., topic_path: Path = Path("topic.json"))` loads `topic = load_topic(topic_path)`
- `discover(sources_path, *, hn_query: str)` — `_fetch_hn` takes the query, sourced from
  `topic["hn_query"]`. `_HN_BASE_PARAMS` drops its hardcoded `query`.
- `rank(articles, *, feedback_path, topic)` and `cluster(articles, *, topic)` receive the dict.
- **`GenerateFn` contract changes** from
  `Callable[[str, str, list[str]], Awaitable[tuple[str, list[str]]]]`
  to
  `Callable[[str, str, list[str], dict], Awaitable[tuple[str, list[str]]]]`
  (appends `topic: dict`).
  - `generate_episode(batch_key, title, urls, topic)` — notebook name becomes
    `f"{topic['short_name']} - {title}"`; instructions become
    `f"{topic['generation_instructions']} Topic: {title}"`.
  - The `_mock_generate` stub in `main.py` gains the matching `topic` param.

### Admin "Topic" page

- Nav link added to `base.html` (`<a href="/admin/topic">Topic</a>`).
- `GET /admin/topic` → form prefilled from `load_topic(app.state.topic_path)`.
  `ranking_criteria` rendered as a `<textarea>`, one criterion per line.
- `POST /admin/topic` (form fields: name, short_name, feed_title, hn_query,
  ranking_criteria textarea, generation_instructions):
  - split `ranking_criteria` textarea on newlines, strip, drop blank lines → `list[str]`
  - call `save_topic(...)`; on `ValueError` return **422** with the message
  - on success redirect `303` back to `/admin/topic`
- `app.state.topic_path` added in `main.py` (`Path("topic.json")`).
- "Reset to Data Engineering defaults" button is **out of scope for v1**.

### Feed title gap (call out explicitly)

The RSS feed title shown in the podcast app does **not** flow from `topic.json` in v1. The
feed is a separate container: `feed/main.py:21` reads `FEED_TITLE` from the environment once
at startup and uses it at `feed/main.py:55` (`fg.title(FEED_TITLE)`). The feed service mounts
no config and never reads `topic.json`.

So for "New Car" / "World Events", the feed would still present as **DE Daily** unless
`FEED_TITLE` in `.env` is changed too. This partially breaks the "via config, not code" goal.

**v1 decision:** keep `feed_title` in `topic.json` as the documented source of truth, but
require `FEED_TITLE` in `.env` to be changed in lockstep. Step E docs must state this
explicitly (a hand-off owner edits both `config/topic.json` and `.env: FEED_TITLE`).

**Follow-up (out of scope for v1):** wire `feed_title` into the feed service so the env var
is no longer needed — e.g. mount `config/topic.json` into the feed container and have
`feed/main.py` read `feed_title` (falling back to `FEED_TITLE`, then `"DE Daily"`). Tracked
as a separate task; not part of these steps.

### Docker

Mount `./config/topic.json:/app/topic.json` in `docker-compose.yml` pipeline service,
mirroring the existing `./config/sources.json:/app/sources.json` line. **Step E must create
and commit `config/topic.json`** (populated with the DE defaults) before the mount lands — a
bind mount to a missing host file is a footgun, and committing it makes the active config
visible/editable rather than relying on the in-code default fallback.

### Tests

- `tests/test_topic.py`: load-when-absent returns defaults; load valid file; each invalid
  field (empty string, missing key, empty list, non-list criteria, empty `feed_title`) raises
  `ValueError`; `save_topic` round-trips and rejects invalid input; admin form round-trips
  `feed_title` (GET prefill and POST save).
- Update `tests/test_ranking.py`, `tests/test_clustering.py` to pass a topic dict and assert
  `name` / criteria appear in the built system prompt.
- Update `tests/test_discovery.py` to assert `hn_query` reaches the HN request params.
- Update `tests/test_pipeline.py` / `tests/test_main.py` for the new `GenerateFn` arg.
- Existing default-path behavior stays green because `load_topic` falls back to DE defaults.

---

## Enhancement 1 — Pin a URL to the next run (build second)

**Goal:** Force-add a specific URL to the next pipeline run, auto-scored 1.0, bypassing
the 48h recency and seen-URL filters, but still passed through `cluster()` so it lands
in a thematic batch.

### Where it fits in the flow

`discover → seen-filter → rank → cluster (needs ≥2) → generate → mark seen`

Pinned URLs skip discover's filters, skip Claude scoring (force 1.0), survive `rank()`'s
top-10 cap, then flow normally into `cluster()` and `generate()`.

### Pinned article dict shape (must match rank/cluster/feed expectations)

When `run_pipeline` injects a pinned entry, it builds the **full** article shape that
ranked articles carry downstream, so clustering, feed tags, and feedback all behave:

```python
{
    "url": entry["url"],
    "title": entry["title"],
    "source": "Pinned",
    "published_at": datetime.now(UTC),
    "snippet": "",
    "score": 1.0,
    "topic_tags": ["pinned"],
    "reason": "Pinned by user",
}
```

`topic_tags: ["pinned"]` is deliberate — without it, feed/feedback tags for a pinned-only
batch would be empty.

### `pipeline/pinned.py` (mirrors `pipeline/sources.py`)

- `load_pinned(path) -> list[dict]` — entries `{"id", "url", "title"}`, auto-slug `id`
  from title like sources does.
- `add_pinned(url, title, *, path) -> dict` — both required; raise `ValueError` on empty
  title; raise `ValueError` if url is empty, not http/https, or has no netloc (validated
  via `urllib.parse.urlparse`: scheme in `{"http", "https"}`, `netloc` non-empty after
  strip); strip url and title before save; dedup by URL (return existing on duplicate,
  no-op write).
- `remove_pinned(id, *, path)` — raise `KeyError` if not found.
- `clear_consumed(urls: set[str], *, path)` — drop entries whose `url` is in `urls`.
- Default path `data/pinned_urls.json`. Pure JSON CRUD — no HTML fetching.

### Wire into `pipeline/pipeline.py` `run_pipeline()`

- Add `pinned_path: Path = Path("data/pinned_urls.json")` param; `app.state.pinned_path` in `main.py`.
- After discover + seen-filter, **pinned wins on URL collision** — exclude naturally-discovered
  articles whose URL matches a pinned entry (not the reverse), so the pinned dict (with
  `score: 1.0`, `source: "Pinned"`, etc.) is always the one that reaches `cluster()`:

  ```python
  pinned_urls = {p["url"] for p in pinned_articles}
  non_pinned = [a for a in articles if a["url"] not in pinned_urls]
  ranked = await rank(non_pinned, feedback_path=feedback_path, topic=topic)
  candidates = _merge_pinned(pinned_articles, ranked)  # pinned first, dedup by URL, cap 10
  if len(candidates) < 2:
      # noop — can't form 2 batches (correct; document with comment)
      ...
  clusters = await cluster(candidates, topic=topic)
  ```

  `_merge_pinned` puts pinned first so they always survive the top-10 cap.
- The `len(candidates) < 2` noop guard applies to the **merged** list: a single pinned URL
  with no other articles still can't form 2 batches. **This is correct/intended** — and the
  naming above prevents accidentally nooping when two pinned URLs exist but `ranked` is short.
  Document it in a comment.

### Cleanup — clustered ≠ consumed

NotebookLM can skip unaddable sources, so a pinned URL that lands in a batch is not
necessarily ingested. Pinned entries clear **only if their URL is in `consumed_urls`**,
i.e. the same `seen_to_add` set used for seen-marking:

```python
if seen_to_add:
    _save_seen(seen_path, seen_urls | seen_to_add)
    clear_consumed(seen_to_add, path=pinned_path)
```

A pinned URL that was skipped by NotebookLM stays pinned and is retried next run — same
semantics as the seen-URL logic. Make this explicit in code + comment.

### Admin UI — "Pinned URLs" section on `sources.html`

Placement: a section below the sources table. Behavior to specify:

- List displays **title + URL** for each pinned entry, with a Delete button.
- Section copy notes: *"Pinned URLs are force-added to the next successful run, scored
  highly, and cleared once ingested."*
- `POST /admin/pinned` (form: url, title — both required):
  - empty/invalid url or title → **422**
  - duplicate URL → returns/links the existing item (no-op), not an error
  - success → redirect `303` to `/admin/sources`
- `DELETE /admin/pinned/{id}`:
  - missing id → **404**
  - success → **204**
- `app.state.pinned_path` read in the sources page handler; template gets `pinned` list.

### Tests

- `tests/test_pinned.py`: CRUD; both-required validation; invalid URL cases (empty, `ftp://`,
  no netloc, non-http scheme) raise `ValueError`; duplicate-URL no-op returns existing;
  `remove_pinned` raises `KeyError` on missing id; `clear_consumed` drops only matching URLs
  and leaves others intact.
- Extend `tests/test_pipeline.py`: pinned URL bypasses the seen-filter; appears in the
  `cluster()` input; survives the top-10 cap; cleared only when in `consumed_urls`
  (and **not** cleared when NotebookLM skipped it).
- Extend `tests/test_admin.py`: 422 on empty fields, 404 on missing delete, duplicate no-op.

**Tradeoff:** pinned URLs skip Claude's quality scoring entirely. Intentional (you're the
curator), but a bad pin can weaken a cluster.

---

## Build order (PR-sized steps)

Topic plumbing first; pinned URLs against the updated contracts.

- **Step A** — `topic.py` load/save/defaults/validation + `tests/test_topic.py`
- **Step B** — thread topic into discovery / ranking / clustering + their tests
- **Step C** — thread topic into NotebookLM naming/instructions, update `GenerateFn`
  contract + `_mock_generate` + pipeline/main tests
- **Step D** — admin Topic page (route + template) + admin tests
- **Step E** — create + commit `config/topic.json` (DE defaults), docker-compose mount,
  docs (incl. the `FEED_TITLE` lockstep note)
- **Step F** — `pinned.py` CRUD + `tests/test_pinned.py`
- **Step G** — pipeline pinned merge/clear behavior + pipeline tests
- **Step H** — admin Pinned UI (section + routes) + admin tests
