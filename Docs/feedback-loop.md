# Ranker Feedback Loop — Architecture

## Overview

A lightweight feedback mechanism that lets you rate episodes from within your podcast app, stores those signals, and uses them to improve the Claude Haiku ranker's scoring over time via few-shot examples in the prompt.

No new infrastructure. No separate service. Feedback is captured via URLs embedded in each episode's RSS description, handled by the existing pipeline container, and stored as a flat JSON file.

---

## How It Works

### Feedback capture

Each episode's RSS description contains two links:

```
👍 Good episode  →  http://192.168.1.x:8001/feedback/{episode_id}?vote=up
👎 Skip this topic  →  http://192.168.1.x:8001/feedback/{episode_id}?vote=down
```

Pocket Casts and Overcast render episode descriptions. You tap directly from the app while listening — no navigation, no app switching. The link opens a minimal mobile-friendly confirmation page in your browser, records the vote, done.

### Feedback storage (`feedback.json`)

```json
[
  {
    "episode_id": "dbt-testing-data-quality-2026-06-10",
    "title": "dbt, testing, and data quality",
    "topic_tags": ["dbt", "testing", "data quality"],
    "article_urls": ["https://...", "https://..."],
    "vote": "up",
    "timestamp": "2026-06-10T08:23:11Z"
  }
]
```

Stored at `/app/data/feedback.json` inside the pipeline container, on the `pipeline_data` volume so it persists across restarts.

### Ranker prompt injection

When `ranking.py` builds the Claude Haiku prompt, it reads the last 20 feedback entries and injects them as few-shot context:

```python
def build_ranking_prompt(articles, feedback):
    liked = [f for f in feedback if f["vote"] == "up"][-10:]
    disliked = [f for f in feedback if f["vote"] == "down"][-10:]

    liked_context = "\n".join(
        f"- {f['title']} (tags: {', '.join(f['topic_tags'])})"
        for f in liked
    )
    disliked_context = "\n".join(
        f"- {f['title']} (tags: {', '.join(f['topic_tags'])})"
        for f in disliked
    )

    return f"""
You are scoring data engineering articles for inclusion in a daily podcast.

The user has previously enjoyed episodes on these topics:
{liked_context}

The user has previously disliked episodes on these topics:
{disliked_context}

Score the following articles 0.0–1.0 for likely interest. Weight topic similarity
to liked episodes positively, and similarity to disliked episodes negatively.

Return JSON: [{{"url": "...", "score": 0.0, "topic_tags": [...], "reason": "..."}}]

Articles:
{format_articles(articles)}
"""
```

No fine-tuning, no embeddings, no new dependencies. The model gets richer context on each run as feedback accumulates.

---

## New Endpoints

Added to the pipeline container (`main.py`):

```
GET  /feedback/{episode_id}?vote=up|down
     → Records vote to feedback.json
     → Returns mobile confirmation page ("👍 Got it. Episode marked as good.")
     → Idempotent: re-voting overwrites previous vote for that episode

GET  /admin/feedback
     → Feedback history in admin UI
     → Shows vote breakdown, top liked/disliked topic tags
```

---

## Feed Description Template

Updated in `feed/main.py` when generating `feed.xml`:

```python
description = f"""
{episode.description}

---
Was this episode useful?
👍 Yes: {FEED_HOST}/feedback/{episode.id}?vote=up
👎 No: {FEED_HOST}/feedback/{episode.id}?vote=down
"""
```

The `FEED_HOST` env var is already defined (`http://192.168.1.x:8001`) — feedback hits the pipeline container, not the feed container.

---

## File Structure Changes

```
de-podcast/
├── pipeline/
│   ├── feedback.py          # NEW: read/write feedback.json, build few-shot context
│   ├── ranking.py           # UPDATED: accepts feedback context, injects into prompt
│   ├── main.py              # UPDATED: adds /feedback/{id} and /admin/feedback routes
│   └── templates/
│       ├── feedback_confirm.html   # NEW: mobile confirmation page
│       └── dashboard.html          # UPDATED: link to feedback history
│
└── data/
    └── feedback.json        # NEW: persisted on notebooklm_auth volume (gitignored)
```

---

## Data Flow

```
Podcast app (Overcast/Pocket Casts)
  → renders episode description
  → user taps 👍 or 👎 link
      │
      ▼
GET /feedback/{episode_id}?vote=up
  → feedback.py writes to feedback.json
  → returns confirmation page
      │
      ▼
Next morning — ranking.py runs
  → reads feedback.json
  → injects last 20 votes as few-shot context into Haiku prompt
  → ranker scores new articles with preference signal applied
```

---

## Feedback Confirmation Page

Minimal mobile HTML — no frameworks, renders in any phone browser:

```
┌─────────────────────────┐
│                         │
│  👍                     │
│                         │
│  Got it.                │
│  "dbt, testing, and     │
│   data quality"         │
│  marked as a good one.  │
│                         │
│  [← Back to podcast]    │
│                         │
└─────────────────────────┘
```

The "Back to podcast" link is a `x-callback-url` / deep link back to the podcast app if detectable from user-agent, otherwise just a close instruction.

---

## Admin Feedback View (`/admin/feedback`)

Simple table in the admin dashboard:

| Date | Episode | Vote | Topic Tags |
|---|---|---|---|
| Jun 10 | dbt + testing | 👍 | dbt, testing, data quality |
| Jun 09 | Kafka streaming | 👎 | kafka, streaming, flink |
| Jun 08 | Snowflake cost tips | 👍 | snowflake, cost, optimization |

Plus a small summary at the top: "8 👍 / 3 👎 over last 30 days. Top liked tags: dbt, snowflake, orchestration. Top disliked tags: opinion, career."

---

## Volume / Persistence

`feedback.json` is stored inside the pipeline container at `/app/data/feedback.json`, on the existing `notebooklm_auth` named volume. No new volume needed.

Update `docker-compose.yml` volume mount:

```yaml
pipeline:
  volumes:
    - episodes:/app/episodes
    - notebooklm_auth:/root/.notebooklm
    - pipeline_data:/app/data          # feedback.json lives here
    - ./config/sources.json:/app/sources.json
```

Add `pipeline_data` to the named volumes block.

---

## Graceful Degradation

- If `feedback.json` doesn't exist yet (first run), ranker prompt omits the few-shot section entirely — no error, no behavior change
- If fewer than 3 feedback entries exist, few-shot section is omitted (not enough signal to be useful)
- Feedback endpoint failures are logged but never surface as errors to the user — a failed vote write doesn't break anything

---

## Cost Impact

Zero. The few-shot examples add ~200–400 tokens to the ranking prompt. At Haiku pricing that's a fraction of a cent per day — negligible against the existing ~$0.03/month baseline.

---

## Build Order (addendum to main doc)

Insert after step 3 (ranking + clustering) in the main build order:

**3b. Feedback loop**
1. `feedback.py` — read/write `feedback.json`, `build_few_shot_context()`
2. Update `ranking.py` to accept and inject feedback context
3. `/feedback/{id}` endpoint + confirmation page template
4. Update feed description template to include vote links
5. `/admin/feedback` view
6. Verify end-to-end: generate test episode → tap link from phone → confirm vote recorded → verify next ranking prompt includes the signal
