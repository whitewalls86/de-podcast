import json
import os
import shutil
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

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


@app.post("/episodes", dependencies=[Depends(verify_token)])
def add_episode(
    file: UploadFile = File(...),
    title: str = Form(...),
    description: str = Form(""),
    pub_date: str = Form(...),
) -> dict:
    filename = file.filename
    dest = EPISODES_DIR / filename
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    size = dest.stat().st_size
    url = f"{FEED_HOST}/episodes/{filename}"

    episodes = load_episodes()
    episodes.append(
        {
            "filename": filename,
            "title": title,
            "description": description,
            "pub_date": pub_date,
            "url": url,
            "size": size,
        }
    )

    if len(episodes) > MAX_EPISODES:
        to_prune = episodes[:-MAX_EPISODES]
        episodes = episodes[-MAX_EPISODES:]
        for ep in to_prune:
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
    path = EPISODES_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Episode not found")
    return FileResponse(path, media_type="audio/mpeg")
