# DE Daily Podcast Pipeline — Project Brief & Architecture

## Overview

An automated pipeline that discovers the most interesting data engineering articles published in the last 24–48 hours, groups them into two thematic batches, generates a NotebookLM audio overview for each batch, and delivers two MP3 episodes to a private RSS feed accessible over Tailscale.

**Goal:** Wake up to two fresh, listenable DE podcast episodes synced to your phone every morning. Zero manual effort after initial setup.

---

## Constraints & Principles

- **Free to run**: No paid APIs. NotebookLM on a personal Google account (free tier: 3 audio overviews/day). Article sources are free RSS/APIs.
- **Local RSS only**: Feed server reachable via Tailscale only. No cloud hosting. Phone syncs over Tailscale VPN.
- **Isolated from CarTracker**: Entirely separate Docker Compose stack, separate repo, separate ports.
- **Dockerized**: All services run in Docker Desktop on Windows. Portable, shareable on GitHub.
- **Orchestrated by n8n**: n8n container handles scheduling. Pipeline container exposes an HTTP endpoint n8n calls.
- **Ephemeral notebooks**: Create NotebookLM notebook → add sources → generate audio → download MP3 → delete notebook. No accumulation.
- **Graceful failure**: If NotebookLM auth expires or generation fails, log and surface in admin UI. Don't crash silently.
- **Admin UI**: Simple web panel for auth management and source list management. No separate frontend framework — served by the pipeline container.

---

## Tech Stack

| Layer | Tool |
|---|---|
| Orchestration | n8n (Docker container, daily cron) |
| Article discovery | RSS feeds + HN Algolia API + Reddit RSS |
| Article ranking | Claude Haiku via Anthropic API |
| Notebook automation | `notebooklm-py` |
| Audio generation | NotebookLM Audio Overview (free tier) |
| Feed server | FastAPI + `feedgen` |
| Admin UI | FastAPI + Jinja2 templates (served by pipeline container) |
| Re-auth UI | noVNC (browser-based VNC client to headless Chromium) |
| Audio storage | Docker named volume |
| Runtime | Docker Desktop on Windows |
| Container base | `python:3.11-slim` |

---

## Docker Compose Services

```yaml
# docker-compose.yml
services:

  pipeline:
    profiles: [pipeline]
    build: ./pipeline
    ports:
      - "8001:8001"   # pipeline API + admin UI
      - "6080:6080"   # noVNC (re-auth browser)
    volumes:
      - episodes:/app/episodes
      - pipeline_data:/app/data                   # seen_urls.json + feedback.json
      - notebooklm_auth:/root/.notebooklm
      - ./config/sources.json:/app/sources.json   # source list (bind mount — editable)
      - ./config/topic.json:/app/topic.json       # topic config (bind mount — editable)
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - FEED_TOKEN=${FEED_TOKEN}
      - FEED_URL=http://feed:8000
      - FEED_HOST=http://${HOST_LAN_IP}:8000
      - USE_DEV_CLIENT=${USE_DEV_CLIENT:-false}
      - USE_MOCK_GENERATE=${USE_MOCK_GENERATE:-false}
      - MAX_BATCHES=${MAX_BATCHES:-0}
    depends_on:
      - feed

  feed:
    build: ./feed
    ports:
      - "8000:8000"   # RSS feed (accessible via Tailscale)
    volumes:
      - episodes:/app/episodes
    environment:
      - FEED_TOKEN=${FEED_TOKEN}
      - FEED_TITLE=${FEED_TITLE:-DE Daily}
      - FEED_HOST=http://${HOST_LAN_IP}:8000
      - PIPELINE_HOST=http://${HOST_LAN_IP}:8001

  n8n:
    image: n8nio/n8n
    ports:
      - "5678:5678"
    volumes:
      - n8n_data:/home/node/.n8n
    environment:
      - N8N_BASIC_AUTH_ACTIVE=true
      - N8N_BASIC_AUTH_USER=${N8N_USER}
      - N8N_BASIC_AUTH_PASSWORD=${N8N_PASSWORD}

volumes:
  episodes:
  pipeline_data:
  notebooklm_auth:
  n8n_data:
```

**Ports summary:**
| Port | Service | Accessible from |
|---|---|---|
| 8000 | RSS feed | Phone via Tailscale; PC via localhost |
| 8001 | Pipeline API + Admin UI | localhost |
| 5678 | n8n | localhost |
| 6080 | noVNC re-auth | localhost |

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  n8n container  (daily cron, ~6am)                  │
│  POST http://pipeline:8001/pipeline/run             │
└─────────────────┬───────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────┐
│  pipeline container  (port 8001)                    │
│                                                     │
│  /pipeline/run  → discover → rank → cluster         │
│                                                     │
│       [Batch A]              [Batch B]              │
│       NotebookLM             NotebookLM             │
│       notebook               notebook               │
│       → MP3                  → MP3                  │
│       → delete               → delete               │
│                                                     │
│  POST http://feed:8000/episodes  (×2)               │
│                                                     │
│  /admin  → Auth status, source management           │
│  /auth/reauth  → triggers noVNC re-auth flow        │
│  :6080  → noVNC (Chromium for Google login)         │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│  feed container  (port 8000)                        │
│                                                     │
│  POST /episodes  ← pipeline posts MP3 + metadata   │
│  GET  /feed.xml  ← podcast app polls                │
│  GET  /episodes/{filename}  ← audio file serving   │
└──────────────────────┬──────────────────────────────┘
                       │ Tailscale VPN
              ┌────────▼────────┐
              │  Apple Podcasts │
              │  (phone)        │
              └─────────────────┘
```

---

## Component Specifications

### 1. Article Discovery (`pipeline/discovery.py`)

Pulls from the following sources in parallel. Active source list is read from `sources.json` (managed via admin UI).

**Default sources in `sources.json`:**
```json
[
  {"name": "Towards Data Science", "url": "https://towardsdatascience.com/feed", "type": "rss", "active": false},
  {"name": "dbt Blog", "url": "https://www.getdbt.com/blog/rss", "type": "rss", "active": true},
  {"name": "Locally Optimistic", "url": "https://locallyoptimistic.com/feed.xml", "type": "rss", "active": true},
  {"name": "Datafold Blog", "url": "https://www.datafold.com/blog/rss.xml", "type": "rss", "active": true},
  {"name": "DataEngineer.io", "url": "https://dataengineer.io/rss", "type": "rss", "active": true},
  {"name": "Medium DE tag", "url": "https://medium.com/feed/tag/data-engineering", "type": "rss", "active": false},
  {"name": "Hacker News", "url": "https://hn.algolia.com/api/v1/search_by_date", "type": "hn", "active": true},
  {"name": "r/dataengineering", "url": "https://www.reddit.com/r/dataengineering/top/.rss?t=day", "type": "rss", "active": true}
]
```

TDS and Medium are disabled by default — their articles are paywalled, so NotebookLM can't fetch the full content.

The HN query string comes from `topic.json`'s `hn_query` field, so changing the topic automatically re-targets the HN search.

After collecting articles, `discover()` loads `data/blocked_domains.json` (if it exists) and filters out any article whose domain — or parent domain — appears in the blocklist. This list grows automatically when NotebookLM deterministically rejects a source; it can also be hand-edited to remove false positives.

**Output:** List of article dicts: `{title, url, source, published_at, snippet}`

**Dedup:** URL-based dedup across sources. Filter out anything older than 48 hours.

---

### 2. Article Ranking (`pipeline/ranking.py`)

Single Claude Haiku call. Pass all article titles + snippets, return JSON ranked list.

**Ranking criteria** are read from `topic.json`'s `ranking_criteria` array and injected into the Claude system prompt at runtime — changing the topic changes what gets scored highly without touching code. The defaults for a DE-focused topic are:
- Practical/technical depth (not opinion fluff)
- Relevance: Snowflake, dbt, Spark, Databricks, Kafka, pipeline architecture, data quality, orchestration
- Novelty: new releases, new techniques, not rehashed basics
- Source credibility

**Output format:**
```json
[
  {"url": "...", "score": 0.92, "topic_tags": ["dbt", "testing"], "reason": "..."},
  ...
]
```

Take top 10 scored articles forward. Drop anything below 0.5.

---

### 3. Topic Clustering (`pipeline/clustering.py`)

Second Claude Haiku call. Groups top 10 articles into exactly 2 thematic batches.

**Output:**
```json
{
  "batch_a": {
    "title": "dbt, testing, and data quality",
    "urls": ["...", "...", "..."]
  },
  "batch_b": {
    "title": "Streaming architectures and Kafka",
    "urls": ["...", "...", "..."]
  }
}
```

---

### 3b. Feedback Loop (`pipeline/feedback.py`)

A lightweight feedback mechanism that lets you rate episodes from within your podcast app, stores those signals, and uses them to improve ranking over time via few-shot examples in the prompt. No new infrastructure — all handled by the pipeline container.

**How it works:**

Each episode's RSS description contains two links:
```
👍 Good episode  →  http://<tailscale-ip>:8001/feedback/{episode_id}?vote=up
👎 Skip this topic  →  http://<tailscale-ip>:8001/feedback/{episode_id}?vote=down
```

Tapping either link from Apple Podcasts opens a minimal mobile confirmation page, records the vote, done.

**Feedback storage (`/app/data/feedback.json`):**
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

**Ranker prompt injection:**

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

**New endpoints (added to `main.py`):**
```
GET  /feedback/{episode_id}?vote=up|down
     → Records vote to feedback.json
     → Returns mobile confirmation page
     → Idempotent: re-voting overwrites previous vote for that episode

GET  /admin/feedback
     → Feedback history in admin UI (vote breakdown, top liked/disliked tags)
```

**Feed description template update (`feed/main.py`):**
```python
description = f"""
{episode.description}

---
Was this episode useful?
👍 Yes: {PIPELINE_HOST}/feedback/{episode.id}?vote=up
👎 No: {PIPELINE_HOST}/feedback/{episode.id}?vote=down
"""
```

**Graceful degradation:**
- If `feedback.json` doesn't exist yet (first run), the few-shot section is omitted — no error, no behavior change
- If fewer than 3 feedback entries exist, the few-shot section is omitted (insufficient signal)
- A failed vote write is logged but never surfaces as an error to the user

**Cost impact:** Zero. The few-shot examples add ~200–400 tokens to the ranking prompt — a fraction of a cent per day at Haiku pricing.

---

### 4. NotebookLM Generation (`pipeline/notebooklm_gen.py`)

Uses `notebooklm-py`. For each batch, runs the full ephemeral notebook lifecycle:

```python
async def generate_episode(
    batch_key: str, title: str, urls: list[str], topic: dict
) -> tuple[str, list[str]]:
    # Returns (mp3_path, consumed_urls).
    # consumed_urls = URLs NotebookLM accepted; rejected URLs are excluded so
    # the pipeline can leave them unmarked in seen_urls.json for retry.
    client = NotebookLMClient()
    notebook = await client.notebooks.create(name=f"{topic['short_name']} - {title}")
    consumed = []
    for url in urls:
        try:
            await notebook.sources.add_url(url)
            consumed.append(url)
        except Exception:
            pass  # logged; domain recorded if rpc_code == 9
    if not consumed:
        raise NoSourcesAddedError(...)  # no retry — all sources deterministically rejected
    audio = await notebook.generate_audio_overview(
        focus=f"{topic['generation_instructions']} Topic: {title}"
    )
    mp3_path = await audio.download(dest=EPISODES_DIR / f"{batch_key}-{today}.mp3")
    await notebook.delete()
    return mp3_path, consumed
```

**Error handling:**
- Auth failure → surface in admin UI, skip episode, do not crash pipeline
- Generation timeout (>15 min) → **not retried**; `ArtifactInProgressTimeoutError` and `asyncio.TimeoutError` propagate immediately because generation has already started and retrying would consume another daily NotebookLM credit
- All sources deterministically rejected (`rpc_code=9`) → raises `NoSourcesAddedError`, also not retried; domains are recorded in `data/blocked_domains.json`
- Transient failures (network errors, other exceptions) → retried once
- One batch failing never blocks the other

**Generation time:** 3–8 min per notebook, run sequentially. Total: ~10–20 min.

---

### 5. RSS Feed Service (`feed/`)

FastAPI app, port 8000. Always running.

**Endpoints:**
```
POST /episodes
  Body: multipart/form-data { file: MP3, title, description, pub_date }
  Auth: Bearer token
  Action: saves MP3 to /app/episodes/, appends to episodes.json, regenerates feed.xml

GET /feed.xml        → RSS 2.0 + iTunes namespace feed (no auth)
GET /episodes/{f}    → MP3 static file serving (no auth)
GET /health          → {"status": "ok"}
```

**Episode retention:** Last 30 episodes. Older MP3s and entries pruned on each POST.

---

### 6. Admin UI (`pipeline/admin/`)

Served by the pipeline container on port 8001. Simple server-rendered HTML (FastAPI + Jinja2). No React, no build step.

**Routes:**
```
GET  /admin                → dashboard
GET  /admin/sources        → source list + pinned URL management
POST /admin/sources        → add source
DELETE /admin/sources/{id} → remove source
PATCH /admin/sources/{id}  → toggle active/inactive
POST /admin/pinned         → add pinned URL (bypasses discovery filter)
DELETE /admin/pinned/{id}  → remove pinned URL
GET  /admin/topic          → topic config editor
POST /admin/topic          → save topic config
DELETE /admin/seen-urls    → clear seen_urls.json (resets cross-run dedup)
GET  /auth/status          → returns auth health JSON (polled by UI)
POST /auth/refresh         → runs `notebooklm auth refresh` (headless)
POST /auth/reauth          → starts noVNC re-auth session
GET  /auth/reauth/status   → polls whether re-auth completed
```

**Dashboard shows:**
- Auth status badge: 🟢 Valid / 🟡 Expiring / 🔴 Expired
- Last pipeline run: timestamp + success/failure
- Today's episodes: titles + download links
- Quick link to source management

---

### 7. Re-auth Flow (noVNC)

The re-auth flow allows Google login to be completed entirely in the browser — no terminal access needed, works on any OS.

**Container setup (`pipeline/Dockerfile`):**
```dockerfile
# Virtual display + VNC + noVNC
RUN apt-get install -y xvfb x11vnc novnc websockify

# notebooklm-py with Playwright/Chromium
RUN pip install "notebooklm-py[browser]"
RUN playwright install chromium
RUN playwright install-deps chromium
```

**Re-auth flow:**
1. User clicks "Re-authenticate" in admin UI (shown when auth is yellow/red)
2. `POST /auth/reauth` → backend starts Xvfb (virtual display) + x11vnc + websockify
3. Backend runs `notebooklm login` against the virtual display (Chromium opens on Xvfb)
4. Frontend redirects to `http://localhost:6080/vnc.html` — noVNC web client
5. User sees Chromium running in browser tab, completes Google login normally
6. `notebooklm login` saves cookies to the `notebooklm_auth` volume, exits
7. VNC server shuts down, admin UI polls `/auth/status` → flips to green
8. User closes noVNC tab, returns to admin dashboard

**Auth check logic:**
```python
# Requires BOTH checks to avoid false-positive on stale cookie file
result = subprocess.run(
    ["notebooklm", "auth", "check", "--test", "--json"],
    capture_output=True
)
data = json.loads(result.stdout)
is_valid = data["status"] == "ok" and data["checks"]["token_fetch"] == True
```

**Session refresh (headless, no browser needed):**
`POST /auth/refresh` runs `notebooklm auth refresh` — handles the common SIDTS rotation case without any user interaction. The admin UI tries this first before escalating to full re-auth.

---

## File Structure

```
de-podcast/
├── docker-compose.yml
├── .env                          # secrets — gitignored
├── .env.example                  # template — committed
├── README.md
├── config/
│   ├── sources.json              # active source list (bind-mounted, committed with defaults)
│   └── topic.json                # topic config: name, hn_query, ranking_criteria, etc. (bind-mounted)
│
├── pipeline/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                   # FastAPI app (pipeline API + admin UI)
│   ├── pipeline.py               # orchestrator logic
│   ├── discovery.py
│   ├── ranking.py
│   ├── clustering.py
│   ├── dev_client.py             # subprocess-backed Claude client for local dev
│   ├── notebooklm_gen.py
│   ├── feedback.py               # read/write feedback.json, build few-shot context
│   ├── topic.py                  # load/validate/save topic.json
│   ├── pinned.py                 # load/add/remove pinned URLs
│   ├── auth.py                   # auth check, refresh, reauth flow
│   ├── sources.py                # source list CRUD
│   └── templates/                # Jinja2 HTML templates
│       ├── base.html
│       ├── dashboard.html
│       ├── sources.html
│       ├── topic.html            # topic config editor
│       └── feedback.html         # feedback history view (vote confirmation is inline HTML)
│
├── feed/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py                   # FastAPI feed server
│
├── scripts/
│   └── test_pipeline.py          # manual end-to-end smoke test (uses dev client)
│
└── tests/
    ├── test_discovery.py
    ├── test_ranking.py
    ├── test_clustering.py
    ├── test_pipeline.py
    ├── test_main.py
    ├── test_feed.py
    └── integration/              # requires full stack; run with --integration flag
```

---

## Environment Variables

```bash
# .env  (gitignored)
ANTHROPIC_API_KEY=sk-ant-...
USE_DEV_CLIENT=false              # local dev only; routes Claude calls through CLI
USE_MOCK_GENERATE=false           # skip NotebookLM, write fake MP3s (testing)
FEED_TOKEN=<random-string>
HOST_LAN_IP=100.x.x.x            # Tailscale IP of Windows machine (tailscale ip -4)
FEED_TITLE=DE Daily
N8N_USER=admin
N8N_PASSWORD=<password>
MAX_BATCHES=0                     # 0 = no limit; set to 1 to conserve NotebookLM quota
```

```bash
# .env.example  (committed)
ANTHROPIC_API_KEY=
USE_DEV_CLIENT=false
USE_MOCK_GENERATE=false
FEED_TOKEN=
HOST_LAN_IP=
FEED_TITLE=DE Daily
N8N_USER=admin
N8N_PASSWORD=
MAX_BATCHES=0
```

---

## n8n Workflow

**Trigger:** Cron — 6:00 AM daily

**Nodes:**
1. `Cron` → fires at 6am
2. `HTTP Request` → POST `http://pipeline:8001/pipeline/run`
3. `IF` → check `{{ $json.status }}` is not `"success"` and not `"noop"`
4. `Send Email` / `Slack` (on failure) → notify of pipeline error, include `{{ $json.status }}` in message body

**Response status field values:**

| `status` | HTTP | Meaning |
|---|---|---|
| `"success"` | 200 | Both episodes generated — normal run |
| `"noop"` | 200 | Fewer than 2 ranked articles — nothing to publish |
| `"partial"` | 200 | At least one episode generated, at least one failed — worth alerting |
| `"failed"` | 500 | All generation attempts failed — n8n HTTP node flags this automatically |

n8n's HTTP Request node treats any non-2xx as an error automatically. `partial` returns 200, so the IF node must check `body.status` to catch it — use condition `{{ $json.status !== "success" && $json.status !== "noop" }}` to route to the alert branch.

n8n and the pipeline container are on the same Docker network, so `http://pipeline:8001` resolves via Docker DNS.

---

## Phone Setup

Use **Apple Podcasts** — not Overcast or Pocket Casts. Those apps use cloud-based feed fetchers that can't reach Tailscale addresses. Apple Podcasts fetches directly from your device.

1. Install Tailscale on your phone and sign in to the same account as your PC
2. Find your PC's Tailscale IP: `tailscale ip -4` (starts with `100.`)
3. Set `HOST_LAN_IP` to this Tailscale IP in `.env`
4. Allow inbound TCP on port 8000 from the Tailscale subnet in Windows Firewall:
   ```powershell
   New-NetFirewallRule -DisplayName "DE Podcast Feed" -Direction Inbound `
     -Protocol TCP -LocalPort 8000 -RemoteAddress 100.64.0.0/10 -Action Allow
   ```
5. Verify the feed is reachable from your phone's browser: `http://<tailscale-ip>:8000/feed.xml`
6. In Apple Podcasts → **Listen Now** → **Follow a Show** → paste that URL
7. Episodes appear after the morning run syncs to the feed

---

## Testing

```bash
# Unit tests — no Docker required
pytest --ignore=tests/integration

# Integration tests — requires full stack running (USE_MOCK_GENERATE=true recommended)
pytest tests/integration/ --integration
```

CI (`.github/workflows/ci.yml`) runs both: the unit job has no external dependencies; the integration job starts the stack with `USE_MOCK_GENERATE=true` to avoid consuming NotebookLM quota.

---

## Cost Summary

| Component | Cost |
|---|---|
| Claude Haiku (ranking + clustering) | ~$0.20/month (~$0.005/run) |
| NotebookLM audio generation | $0 (free tier) |
| Infrastructure | $0 (local Docker) |
| **Total** | **~$0.03/month** |

---

## Known Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| NotebookLM cookie expiry | Monthly | Admin UI shows status; one-click re-auth via noVNC |
| `notebooklm auth refresh` not enough, full re-auth needed | Monthly | noVNC flow handles it in browser, no terminal needed |
| NotebookLM internal API changes | Low-medium | Pin `notebooklm-py` version; upgrade intentionally |
| Article sources go stale | Low | Admin UI source management; add/remove without redeploy |
| Daily limit hit (3/day free) | Very low | Pipeline uses exactly 2; 1 in reserve |
| Windows machine sleeps | Low | Disable sleep in Windows power settings |

---

## Dev Client (Claude CLI workaround)

During early development, before loading Anthropic API credits, `ranking.py` and `clustering.py` can run against the Claude.ai subscription via the `claude` CLI instead of the paid API. This is a local development workaround, not the production path.

**Toggle:** set `USE_DEV_CLIENT=true` in the local environment (`.env.example` includes this key). When unset or `false`, the normal `anthropic.AsyncAnthropic` client is used. Do not enable this in Docker or n8n; containers should always use the Anthropic API client.

**How it works (`pipeline/dev_client.py`):**

`get_anthropic_client()` is a factory used by `ranking.py` and `clustering.py`. In normal mode it returns `anthropic.AsyncAnthropic`. In dev mode it returns `DevClient`.

`DevClient` implements only the SDK surface this project needs: `client.messages.create(...)` returning an object with `.content[0].text`. Instead of making an API call, it invokes the Claude CLI locally via `asyncio.to_thread`, captures stdout, and wraps it in that minimal response shape so `ranking.py` and `clustering.py` see no difference.

The prompt is passed via stdin to avoid Windows `CreateProcess` command-line length limits (ranking payloads can be large). `--output-format json` wraps the response in a structured envelope, which also yields token usage stats:

```python
subprocess.run(
    ["claude", "-p", "--output-format", "json"],
    input=prompt,
    shell=False,
    capture_output=True,
    text=True,
    timeout=120,
)
```

The JSON envelope has the shape `{"result": "...", "usage": {"input_tokens": N, "output_tokens": N, "cache_read_input_tokens": N, "total_cost_usd": 0.0}}`. `total_cost_usd` is always `0.0` in dev mode because the CLI routes through the Claude.ai subscription rather than the API, so `_log_usage()` computes an estimated API cost from the token counts using actual `claude-haiku-4-5` pricing ($1.00/M input, $5.00/M output, $0.10/M cache read). Each invocation prints a line like:

```
[dev-client] tokens: input=1842, output=312, est. $0.0034
```

This lets you track cumulative cost exposure before switching to paid API credits.

Raises clear errors when `claude` is not installed, exits nonzero, times out, or returns empty output.

```
USE_DEV_CLIENT=true  →  DevClient (subprocess → claude CLI → Claude.ai subscription)
USE_DEV_CLIENT unset →  anthropic.AsyncAnthropic (Anthropic API → API credits)
```

**Known limitations of dev mode:**

- Subject to Claude.ai rate limits — not suitable for high-volume runs.
- Not available inside Docker containers (no `claude` CLI installed there); dev mode is local only.
- This avoids API billing during development, but it still uses model capacity through the logged-in Claude CLI account.
- Estimated costs are based on `claude-haiku-4-5` API rates; actual production costs depend on the model and tier in use.

**Smoke test script (`scripts/test_pipeline.py`):**

Runs `discover()` → `rank()` → `cluster()` end-to-end against live sources and prints a summary (article counts, batch titles). Requires `USE_DEV_CLIENT=true` — exits immediately with a clear message otherwise. Not part of the automated test suite; intended for local validation before committing API credits.

```bash
USE_DEV_CLIENT=true python scripts/test_pipeline.py
```

---

## Cross-Run Deduplication

Discovery uses a rolling 48-hour window, so an article published at 9am Monday is a candidate on both the Monday and Tuesday runs. Without cross-run state, a high-scoring article can appear in two consecutive podcasts.

**Mechanism:** a `data/seen_urls.json` file (Docker volume, persisted across runs) tracks every URL that made it into a final podcast. At the start of each run, `discover()` filters out any URL already in that file. URLs are written per successfully generated batch — if a batch's episode is produced, its URLs are marked seen; if a batch fails, its URLs are left out of `seen_urls.json` so they remain candidates for the next run rather than being silently dropped.

```
data/seen_urls.json  →  ["https://...", "https://...", ...]
```

This lives in the `pipeline/` container under the `pipeline_data` named volume so it persists across container restarts. The Admin UI can expose a "clear seen URLs" action for manual resets (e.g. after a gap in runs).

Implemented in step 4 (pipeline wiring).

---

## Build Order

1. **Feed container** — get `feed/` running, verify `feed.xml` is reachable via Tailscale, add to Apple Podcasts
2. **Discovery** — `discovery.py` pulling and deduping articles from all sources
3. **Ranking + Clustering** — Claude Haiku calls, validate JSON output quality manually
3b. **Feedback loop** — `feedback.py`, update `ranking.py` with few-shot injection, `/feedback/{id}` endpoint + confirmation template, update feed description template, `/admin/feedback` view
4. **Pipeline wiring** — `pipeline.py` end-to-end with mocked NotebookLM; includes cross-run deduplication (`seen_urls.json` read + write on success)
5. **Admin UI** — dashboard, source management, auth status display, "clear seen URLs" action
6. **NotebookLM gen** — `notebooklm login` first-time auth, test single notebook + audio generation
7. **noVNC re-auth** — Dockerfile with Xvfb/VNC/noVNC, test full re-auth flow in browser
8. **n8n workflow** — cron trigger, HTTP call to pipeline, failure notification
9. **Docker Compose** — wire all services, test full stack end to end

Test each layer independently. Mock NotebookLM during steps 1–5 to preserve daily quota.
