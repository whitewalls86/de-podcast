import json
import re
from pathlib import Path
from urllib.parse import urlparse

_DEFAULT_PINNED = Path("data/pinned_urls.json")


def _slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    seen_ids: set[str] = set()
    for entry in data:
        if "id" not in entry:
            base = _slugify(entry["title"])
            eid = base
            n = 1
            while eid in seen_ids:
                eid = f"{base}-{n}"
                n += 1
            entry["id"] = eid
        seen_ids.add(entry["id"])
    return data


def _save(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2))


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc.strip():
        raise ValueError(f"Invalid URL {url!r}: must be http/https with a non-empty host")


def load_pinned(path: Path = _DEFAULT_PINNED) -> list[dict]:
    return _load(path)


def add_pinned(url: str, title: str, *, path: Path = _DEFAULT_PINNED) -> dict:
    url = url.strip()
    title = title.strip()
    if not title:
        raise ValueError("Pinned title must not be empty")
    _validate_url(url)

    entries = _load(path)
    for e in entries:
        if e["url"] == url:
            return e

    base = _slugify(title)
    if not base:
        base = "pinned"
    existing_ids = {e["id"] for e in entries}
    eid = base
    n = 1
    while eid in existing_ids:
        eid = f"{base}-{n}"
        n += 1

    entry = {"id": eid, "url": url, "title": title}
    entries.append(entry)
    _save(path, entries)
    return entry


def remove_pinned(id: str, *, path: Path = _DEFAULT_PINNED) -> None:
    entries = _load(path)
    filtered = [e for e in entries if e["id"] != id]
    if len(filtered) == len(entries):
        raise KeyError(id)
    _save(path, filtered)


def clear_consumed(urls: set[str], *, path: Path = _DEFAULT_PINNED) -> None:
    entries = _load(path)
    remaining = [e for e in entries if e["url"] not in urls]
    if len(remaining) != len(entries):
        _save(path, remaining)
