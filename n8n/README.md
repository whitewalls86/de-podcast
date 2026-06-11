# n8n Workflow

## Overview

`pipeline-workflow.json` is the portable n8n workflow definition for DE Daily. It:

1. Fires at **6:00 AM daily** (cron trigger)
2. POSTs to `http://pipeline:8001/pipeline/run` — resolved via Docker DNS since n8n and the pipeline container share the default Compose network
3. Checks the response `status` field
4. Sends an email alert if status is anything other than `"success"` or `"noop"` (catches `"partial"` and HTTP errors from `"failed"`)

## Prerequisites

- Docker Compose stack running (`docker compose up -d`, with `--profile pipeline` to include the pipeline container)
- n8n reachable at `http://localhost:5678`
- n8n credentials configured for SMTP (see below)

## Import via UI

1. Open n8n at `http://localhost:5678`
2. Go to **Workflows → Import from File**
3. Select `n8n/pipeline-workflow.json`
4. Configure the **Send Alert Email** node credentials (see below)
5. Set the two workflow variables (see below)
6. Click **Activate** to enable the schedule

## Import via API

```bash
curl -X POST http://localhost:5678/api/v1/workflows \
  -H "Content-Type: application/json" \
  -u "${N8N_USER}:${N8N_PASSWORD}" \
  -d @n8n/pipeline-workflow.json
```

After importing, activate it:

```bash
# Get the workflow ID from the import response, then:
curl -X PATCH http://localhost:5678/api/v1/workflows/<id>/activate \
  -u "${N8N_USER}:${N8N_PASSWORD}"
```

## Configure Email Alerts

The **Send Alert Email** node uses SMTP. Set up a credential in n8n:

1. Go to **Settings → Credentials → New Credential → SMTP**
2. For Gmail with an App Password:
   - **Host:** `smtp.gmail.com`
   - **Port:** `465`
   - **SSL/TLS:** enabled
   - **User:** your Gmail address
   - **Password:** a Gmail [App Password](https://myaccount.google.com/apppasswords) (not your account password)
3. Name it **"SMTP (configure me)"** to match the credential name in the workflow, or update the node to point to whatever you name it

Then set two **workflow variables** (in the workflow editor under the gear icon):

| Variable | Value |
|---|---|
| `ALERT_FROM_EMAIL` | your Gmail address |
| `ALERT_TO_EMAIL` | address to receive alerts |

## Status Values

| `status` field | HTTP | Alert sent? |
|---|---|---|
| `success` | 200 | No |
| `noop` | 200 | No (fewer than 2 articles ranked) |
| `partial` | 200 | **Yes** — at least one batch failed |
| `failed` | 500 | **Yes** — HTTP node marks as error, IF catches undefined status |

## Timeout

The HTTP Request node has a 30-minute timeout (1 800 000 ms). The pipeline typically completes in 10–20 minutes (two NotebookLM notebooks sequentially at 3–8 min each). Adjust in the **Run Pipeline** node → Options → Timeout if needed.

## Docker Network Note

n8n calls `http://pipeline:8001` using Docker's internal DNS — this only works when both containers are running on the same Compose stack. The pipeline service uses `profiles: [pipeline]`, so start it with:

```bash
docker compose --profile pipeline up -d
```

Without the profile flag, the pipeline container won't start and n8n's HTTP call will fail with a connection error.
