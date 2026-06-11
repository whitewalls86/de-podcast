# Step 9 — Full Docker Compose Integration Test Plan

The goal is to prove the entire stack works end-to-end in Docker: real containers, real network, real NotebookLM auth, real audio generation. Steps 6 (NotebookLM gen) and 7 (noVNC re-auth) are code-complete but unproven in Docker — this is the session that confirms them.

---

## Phase 1 — Pre-flight

- [ ] `docker compose --profile pipeline build` — verify all images build cleanly (no missing deps, no Dockerfile errors)
- [ ] `docker compose --profile pipeline up -d` — all 4 containers start (`feed`, `pipeline`, `n8n`, any dependencies)
- [ ] `docker compose ps` — all containers show healthy/running, no restart loops
- [ ] `curl http://localhost:8000/health` — feed responds
- [ ] `curl http://localhost:8001/admin` — pipeline admin UI loads
- [ ] `curl http://localhost:5678` — n8n UI is up

---

## Phase 2 — NotebookLM Auth (Step 7 proof)

- [ ] Open `http://localhost:8001/admin` — auth badge shows status (🟡 Expiring or 🔴 Expired on first run)
- [ ] Click **Re-authenticate** → page redirects to `http://localhost:6080/vnc.html`
- [ ] Chromium is visible in the noVNC tab; Google login flow is reachable
- [ ] Complete Google login — cookies are saved to the `notebooklm_auth` volume
- [ ] Admin UI polls `/auth/status` and flips to 🟢 Valid without a page reload
- [ ] Verify auth persists across a container restart: `docker compose restart pipeline` → badge stays green

---

## Phase 3 — Pipeline Run (Step 6 proof)

- [ ] From admin UI or curl: `curl -X POST http://localhost:8001/pipeline/run`
- [ ] Watch logs: `docker compose logs -f pipeline` — confirm discovery → ranking → clustering → NotebookLM notebook creation → audio generation → MP3 download → notebook deletion for both batches
- [ ] Response body contains `{"status": "success"}` (or `"partial"` if one batch fails — investigate if so)
- [ ] `curl http://localhost:8000/feed.xml` — feed contains 2 new episodes with correct titles and MP3 links
- [ ] `curl http://localhost:8000/episodes/<filename>.mp3` — audio file is served and playable

---

## Phase 4 — n8n Workflow

- [ ] Import `n8n/pipeline-workflow.json` via n8n UI
- [ ] Configure SMTP credential and workflow variables
- [ ] **Manual trigger** the workflow — confirm it POSTs to pipeline and completes without error
- [ ] Temporarily change the IF condition to always-true and re-trigger — verify alert email arrives
- [ ] Restore condition, activate the workflow for real scheduling

---

## Phase 5 — Cross-run Deduplication

- [ ] Run the pipeline a second time the same day — confirm the same URLs don't appear in a second episode
- [ ] Check `docker compose exec pipeline cat /app/data/seen_urls.json` — URLs from the first run are present
- [ ] Admin UI **Clear Seen URLs** action — clears the file; next run re-discovers the same articles

---

## Phase 6 — Phone / LAN Access

- [ ] From a phone on home WiFi: open `http://<HOST_LAN_IP>:8000/feed.xml` in the browser — feed XML loads
- [ ] Add the feed URL to Overcast or Pocket Casts — episodes appear and are playable over WiFi
- [ ] Tap a 👍/👎 feedback link from within the podcast app — confirmation page loads, vote recorded in `/app/data/feedback.json`

---

## Known Risks

| Risk | Signal | Fix |
|---|---|---|
| NotebookLM free tier daily limit (3/day) | generation fails with quota error | Run at off-peak time or on a day with no prior usage |
| `notebooklm-py` API change | auth or notebook creation throws unexpectedly | Pin version in requirements.txt; check PyPI for newer release |
| noVNC not binding port 6080 | `curl localhost:6080` refuses | Check Dockerfile Xvfb/websockify setup; inspect pipeline container logs |
| Pipeline container can't reach `feed:8000` | episode POST fails in logs | Confirm both services are on the same Compose network; check `depends_on` |
