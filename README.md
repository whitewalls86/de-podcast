# DE Daily Podcast Pipeline

Automated pipeline that discovers interesting data engineering articles, groups them into thematic batches, generates NotebookLM audio overviews, and delivers MP3 episodes to a local private RSS feed.

## Setup

1. Copy `.env.example` to `.env` and fill in values
2. Find your LAN IP: `ipconfig` → IPv4 address of your network adapter
3. Start the feed and n8n services (pipeline is added in a later build step):
   ```
   docker compose up -d
   ```
4. Once the pipeline service is built, start the full stack:
   ```
   docker compose --profile pipeline up -d
   ```

## Services

| Port | Service |
|------|---------|
| 8000 | RSS feed (LAN — add to Overcast/Pocket Casts) |
| 8001 | Pipeline API + Admin UI |
| 5678 | n8n workflow editor |
| 6080 | noVNC (NotebookLM re-auth) |

## Build Order

See `Docs/de-podcast-pipeline.md` for full architecture and step-by-step build order.

## Cost

~$0.03/month (Claude Haiku for ranking/clustering; everything else free).
