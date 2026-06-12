import asyncio
import calendar
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import feedparser
import httpx
from dateutil import parser as dateutil_parser

_HN_BASE_PARAMS = {"tags": "story", "hitsPerPage": "30"}
_RSS_TIMEOUT = 15
_SNIPPET_MAX = 300

logger = logging.getLogger(__name__)


def _cutoff() -> datetime:
    return datetime.now(tz=UTC) - timedelta(hours=48)


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _snippet(text: str | None) -> str:
    if not text:
        return ""
    return text[:_SNIPPET_MAX]


def _normalized_domain(url: str) -> str | None:
    hostname = urlparse(url).hostname
    if not hostname:
        return None
    domain = hostname.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain or None


async def _fetch_rss(source: dict) -> list[dict]:
    async with httpx.AsyncClient(timeout=_RSS_TIMEOUT, follow_redirects=True) as client:
        r = await client.get(source["url"])
        r.raise_for_status()
        content = r.content
    feed = await asyncio.to_thread(feedparser.parse, content)
    results = []
    for entry in feed.entries:
        url = entry.get("link", "")
        if not url:
            continue
        published_parsed = entry.get("published_parsed")
        if published_parsed:
            published_at: datetime | None = datetime.fromtimestamp(
                calendar.timegm(published_parsed), tz=UTC
            )
        else:
            published_at = None
            for field in ("published", "updated"):
                raw = entry.get(field)
                if raw:
                    try:
                        published_at = _to_utc(dateutil_parser.parse(raw))
                        break
                    except Exception:
                        pass
        if published_at is None:
            continue
        results.append(
            {
                "title": entry.get("title", ""),
                "url": url,
                "source": source["name"],
                "published_at": published_at,
                "snippet": _snippet(entry.get("summary") or entry.get("description")),
            }
        )
    return results


async def _fetch_hn(source: dict, *, hn_query: str) -> list[dict]:
    cutoff_ts = int(_cutoff().timestamp())
    params = {**_HN_BASE_PARAMS, "query": hn_query, "numericFilters": f"created_at_i>{cutoff_ts}"}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(source["url"], params=params)
        r.raise_for_status()
        data = r.json()
    results = []
    for hit in data.get("hits", []):
        url = hit.get("url", "")
        if not url:
            continue
        raw_date = hit.get("created_at")
        if not raw_date:
            continue
        try:
            published_at = _to_utc(dateutil_parser.parse(raw_date))
        except Exception:
            continue
        results.append(
            {
                "title": hit.get("title", ""),
                "url": url,
                "source": source["name"],
                "published_at": published_at,
                "snippet": _snippet(hit.get("story_text")),
            }
        )
    return results


async def discover(
    sources_path: Path,
    *,
    hn_query: str,
    blocked_domains_path: Path = Path("data/blocked_domains.json"),
) -> list[dict]:
    blocked: set[str] = set()
    if blocked_domains_path.exists():
        try:
            blocked = set(json.loads(blocked_domains_path.read_text()))
        except (json.JSONDecodeError, ValueError):
            logger.warning("blocked_domains.json is malformed; treating as empty")

    sources = json.loads(sources_path.read_text())
    active = [s for s in sources if s.get("active", True)]

    tasks = []
    for source in active:
        if source["type"] == "rss":
            tasks.append(_fetch_rss(source))
        elif source["type"] == "hn":
            tasks.append(_fetch_hn(source, hn_query=hn_query))

    results_per_source = await asyncio.gather(*tasks, return_exceptions=True)

    cutoff = _cutoff()
    seen: dict[str, dict] = {}
    for result in results_per_source:
        if isinstance(result, Exception):
            continue
        for article in result:
            url = article["url"]
            if url not in seen and article["published_at"] >= cutoff:
                seen[url] = article

    if not blocked:
        return list(seen.values())

    def _is_blocked(url: str) -> bool:
        domain = _normalized_domain(url)
        if not domain:
            return False
        return any(domain == b or domain.endswith("." + b) for b in blocked)

    return [a for a in seen.values() if not _is_blocked(a["url"])]
