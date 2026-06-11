import json
import os
import shutil
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from feedgen.feed import FeedGenerator

EPISODES_DIR = Path(os.environ.get("EPISODES_DIR", "/app/episodes"))
EPISODES_JSON = EPISODES_DIR / "episodes.json"
FEED_XML = EPISODES_DIR / "feed.xml"
MAX_EPISODES = 30

FEED_TOKEN = os.environ.get("FEED_TOKEN", "")
FEED_HOST = os.environ.get("FEED_HOST", "http://localhost:8000")
FEED_TITLE = os.environ.get("FEED_TITLE", "DE Daily")
PIPELINE_HOST = os.environ.get("PIPELINE_HOST", "http://localhost:8001")

security = HTTPBearer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    EPISODES_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="DE Daily Feed", lifespan=lifespan)


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> None:
    if credentials.credentials != FEED_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")


def load_episodes() -> list[dict]:
    if not EPISODES_JSON.exists():
        return []
    return json.loads(EPISODES_JSON.read_text())


def save_episodes(episodes: list[dict]) -> None:
    EPISODES_JSON.write_text(json.dumps(episodes, indent=2))


def regenerate_feed(episodes: list[dict]) -> None:
    fg = FeedGenerator()
    fg.load_extension("podcast")
    fg.id(f"{FEED_HOST}/feed.xml")
    fg.title(FEED_TITLE)
    fg.link(href=f"{FEED_HOST}/feed.xml", rel="self")
    fg.language("en")
    fg.description("Daily data engineering podcast from top articles.")
    fg.podcast.itunes_category("Technology")  # type: ignore[attr-defined]
    fg.podcast.itunes_explicit("no")  # type: ignore[attr-defined]

    for ep in reversed(episodes):
        fe = fg.add_entry()
        fe.id(ep["url"])
        fe.title(ep["title"])
        fe.description(ep.get("description", ""))
        pub = datetime.fromisoformat(ep["pub_date"])
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=UTC)
        fe.published(pub)
        fe.enclosure(ep["url"], str(ep.get("size", 0)), "audio/mpeg")

    fg.rss_file(str(FEED_XML))


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


def safe_filename(raw: str | None) -> str:
    """Return a sanitized basename, rejecting path separators."""
    name = Path(raw or "episode.mp3").name
    if not name or name in (".", ".."):
        raise HTTPException(status_code=422, detail="Invalid filename")
    return name


def _dest_safe(filename: str) -> Path:
    """Resolve destination and assert it stays inside EPISODES_DIR."""
    dest = (EPISODES_DIR / filename).resolve()
    if not dest.is_relative_to(EPISODES_DIR.resolve()):
        raise HTTPException(status_code=422, detail="Invalid filename")
    return dest


@app.post("/episodes", dependencies=[Depends(verify_token)])
def add_episode(
    file: UploadFile = File(...),
    title: str = Form(...),
    description: str = Form(""),
    pub_date: str = Form(...),
    episode_id: str = Form(""),
    tags: str = Form(""),
) -> dict:
    try:
        pub_dt = datetime.fromisoformat(pub_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid pub_date — expected ISO 8601")
    if pub_dt.tzinfo is None:
        pub_dt = pub_dt.replace(tzinfo=UTC)

    if episode_id:
        vote_title = quote(title, safe="")
        vote_tags = quote(tags, safe="")
        vote_base = f"{PIPELINE_HOST}/feedback/{episode_id}"
        description = (
            description + f"\n\n---\nWas this episode useful?\n"
            f"👍 Yes: {vote_base}?vote=up&title={vote_title}&tags={vote_tags}\n"
            f"👎 No: {vote_base}?vote=down&title={vote_title}&tags={vote_tags}"
        )

    filename = safe_filename(file.filename)
    if not filename.lower().endswith(".mp3") or file.content_type != "audio/mpeg":
        raise HTTPException(status_code=415, detail="Only audio/mpeg (.mp3) uploads are accepted")
    dest = _dest_safe(filename)

    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    size = dest.stat().st_size
    url = f"{FEED_HOST}/episodes/{quote(filename, safe='')}"

    entry = {
        "filename": filename,
        "title": title,
        "description": description,
        "pub_date": pub_date,
        "url": url,
        "size": size,
    }

    episodes = load_episodes()
    # Replace existing entry for the same filename (same-day rerun), else append.
    existing = next((i for i, e in enumerate(episodes) if e["filename"] == filename), None)
    if existing is not None:
        episodes[existing] = entry
    else:
        episodes.append(entry)

    if len(episodes) > MAX_EPISODES:
        to_prune = episodes[:-MAX_EPISODES]
        episodes = episodes[-MAX_EPISODES:]
        retained = {e["filename"] for e in episodes}
        for ep in to_prune:
            if ep["filename"] not in retained:
                old = EPISODES_DIR / ep["filename"]
                if old.exists():
                    old.unlink()

    save_episodes(episodes)
    regenerate_feed(episodes)

    return {"status": "ok", "url": url}


@app.get("/feed.xml")
def get_feed() -> FileResponse:
    if not FEED_XML.exists():
        raise HTTPException(status_code=404, detail="No feed yet — post an episode first")
    return FileResponse(FEED_XML, media_type="application/rss+xml")


@app.get("/episodes/{filename}")
def get_episode(filename: str) -> FileResponse:
    retained = {e["filename"] for e in load_episodes()}
    if filename not in retained:
        raise HTTPException(status_code=404, detail="Episode not found")
    path = EPISODES_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Episode not found")
    return FileResponse(path, media_type="audio/mpeg")
