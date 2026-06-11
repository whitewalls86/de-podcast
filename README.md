# DE Daily Podcast Pipeline

Automated pipeline that discovers data engineering articles, ranks them with Claude Haiku, clusters them into two thematic batches, generates NotebookLM audio overviews, and delivers MP3 episodes to a private RSS feed on your phone.

Runs daily via n8n. Phone subscribes via Apple Podcasts over Tailscale. Cost: ~$0.03/month.

---

## Prerequisites

- **Docker Desktop** (Windows)
- **Tailscale** installed on both your PC and phone — required for the podcast app to reach your local feed server
- **Google account** for NotebookLM (free tier: 3 audio overviews/day)
- **Anthropic API key** — [console.anthropic.com](https://console.anthropic.com) (Claude Haiku, ~$0.03/month)

---

## Setup

### 1. Clone and configure

```
git clone https://github.com/whitewalls86/de-podcast
cd de-podcast
copy .env.example .env
```

Edit `.env`:

```bash
ANTHROPIC_API_KEY=sk-ant-...
FEED_TOKEN=<any-random-string>        # auth token for episode uploads
HOST_LAN_IP=<your-tailscale-ip>       # find it: tailscale ip -4
FEED_TITLE=DE Daily
N8N_USER=admin
N8N_PASSWORD=<choose-a-password>
```

`HOST_LAN_IP` must be your **Tailscale IP** (starts with `100.`), not your LAN IP — podcast apps on your phone use cloud fetchers that can't reach plain LAN addresses.

### 2. Open Windows Firewall for port 8000

The feed runs on port 8000. Allow inbound TCP from the Tailscale subnet:

```powershell
New-NetFirewallRule -DisplayName "DE Podcast Feed" -Direction Inbound `
  -Protocol TCP -LocalPort 8000 -RemoteAddress 100.64.0.0/10 -Action Allow
```

### 3. Start the stack

```
docker compose up -d                          # feed + n8n
docker compose --profile pipeline up -d      # add pipeline container
```

Wait for containers to be healthy:
```
docker compose ps
```

### 4. Re-authenticate NotebookLM

The first run requires a Google login via the browser-based re-auth flow:

1. Open the Admin UI: [http://localhost:8001/admin](http://localhost:8001/admin)
2. If the auth badge shows yellow or red, click **Re-authenticate**
3. You're redirected to noVNC at [http://localhost:6080](http://localhost:6080) — a Chromium window running inside the container
4. Complete the Google login normally
5. Return to the Admin UI — the badge should flip to green

Auth cookies are stored in a Docker named volume and persist across restarts. Re-auth is typically needed monthly.

### 5. Set up n8n

1. Open n8n: [http://localhost:5678](http://localhost:5678) (login with `N8N_USER` / `N8N_PASSWORD`)
2. Create a workflow:
   - **Cron** node — 6:00 AM daily
   - **HTTP Request** node — POST `http://pipeline:8001/pipeline/run`
   - **IF** node — condition: `{{ $json.status !== "success" && $json.status !== "noop" }}`
   - **notification node** (optional) — alert on partial failure

### 6. Add the feed to Apple Podcasts

Use **Apple Podcasts** — not Overcast or Pocket Casts, which use cloud fetchers that can't reach Tailscale addresses.

1. Find your Tailscale IP: `tailscale ip -4`
2. Verify the feed is reachable from your phone's browser: `http://<tailscale-ip>:8000/feed.xml`
3. In Apple Podcasts → **Listen Now** → **Follow a Show** → paste the URL

### 7. Trigger a test run

From the Admin UI or via curl:
```
curl -X POST http://localhost:8001/pipeline/run
```

Check the Admin UI dashboard for run status and today's episodes. Full generation takes 10–20 minutes (NotebookLM audio is slow).

**To test without consuming NotebookLM quota**, set `USE_MOCK_GENERATE=true` in `.env` and restart the pipeline container — fake MP3s are written instead.

---

## Services

| Port | Service | Access |
|------|---------|--------|
| 8000 | RSS feed | Phone via Tailscale; PC via localhost |
| 8001 | Pipeline API + Admin UI | localhost |
| 5678 | n8n workflow editor | localhost |
| 6080 | noVNC (NotebookLM re-auth) | localhost |

---

## Testing

```bash
# Unit tests only (no Docker required)
pytest --ignore=tests/integration

# Full integration tests (requires stack running)
pytest tests/integration/ --integration
```

CI runs both on PRs and on pushes to `master`/`implementation` (integration job uses `USE_MOCK_GENERATE=true`).

---

## Key env vars

| Variable | Default | Purpose |
|----------|---------|---------|
| `HOST_LAN_IP` | — | Tailscale IP of your PC (e.g. `100.x.x.x`) |
| `FEED_TOKEN` | — | Bearer token for episode upload auth |
| `ANTHROPIC_API_KEY` | — | Claude Haiku for ranking and clustering |
| `USE_MOCK_GENERATE` | `false` | Skip NotebookLM, write fake MP3s (testing) |
| `MAX_BATCHES` | `0` (no limit) | Cap NotebookLM generations per run (`1` to conserve quota) |
| `USE_DEV_CLIENT` | `false` | Local dev only — routes Claude calls through CLI instead of API |

---

## Cost

~$0.20/month (Claude Haiku for ranking/clustering; everything else free).
Measured: ~$0.005/run on a typical day (ranking ~1,400 input + ~500 output tokens; clustering ~400 input + ~170 output tokens).
