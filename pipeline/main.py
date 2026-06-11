import logging
from html import escape
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from pipeline.admin import router as admin_router
from pipeline.auth import get_auth_status, refresh_auth, start_reauth
from pipeline.feedback import DEFAULT_FEEDBACK, record_vote
from pipeline.pipeline import run_pipeline

logger = logging.getLogger(__name__)

app = FastAPI()
app.state.sources_path = Path("sources.json")
app.state.last_run_path = Path("data/last_run.json")
app.state.feedback_path = DEFAULT_FEEDBACK

app.include_router(admin_router)

_VOTE_HTML = """\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Thanks for your feedback!</title>
  <style>
    body {{ font-family: sans-serif; text-align: center; padding: 3rem;
            max-width: 500px; margin: auto; }}
  </style>
</head>
<body>
  <h1>{emoji} Thanks!</h1>
  <p>Your feedback on <strong>{title}</strong> was recorded.</p>
  <p><a href="/admin/feedback">View all feedback</a></p>
</body>
</html>
"""


@app.get("/feedback/{episode_id}", response_class=HTMLResponse)
async def feedback_vote(
    episode_id: str,
    vote: str,
    request: Request,
    title: str = "",
    tags: str = "",
) -> str:
    if vote not in ("up", "down"):
        raise HTTPException(status_code=422, detail="vote must be 'up' or 'down'")

    topic_tags = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    try:
        record_vote(
            episode_id,
            title,
            topic_tags,
            [],
            vote,
            path=request.app.state.feedback_path,
        )
    except Exception:
        logger.exception("Failed to record vote for episode %s", episode_id)

    emoji = "👍" if vote == "up" else "👎"
    return _VOTE_HTML.format(emoji=emoji, title=escape(title or episode_id))


@app.post("/pipeline/run")
async def pipeline_run(request: Request):
    result = await run_pipeline(feedback_path=request.app.state.feedback_path)
    if result["status"] == "failed":
        raise HTTPException(status_code=500, detail=result)
    return result


@app.get("/auth/status")
async def auth_status():
    return get_auth_status()


@app.post("/auth/refresh")
async def auth_refresh():
    return await refresh_auth()


@app.post("/auth/reauth")
async def auth_reauth():
    return await start_reauth()


@app.get("/health")
async def health():
    return {"status": "ok"}
