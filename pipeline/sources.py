import json
import re
from pathlib import Path

_DEFAULT_SOURCES = Path("sources.json")
_VALID_TYPES = {"rss", "hn"}


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    seen_ids: set[str] = set()
    for source in data:
        if "id" not in source:
            base = _slugify(source["name"])
            sid = base
            n = 1
            while sid in seen_ids:
                sid = f"{base}-{n}"
                n += 1
            source["id"] = sid
        seen_ids.add(source["id"])
    return data


def _save(path: Path, sources: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sources, indent=2))


def list_sources(path: Path = _DEFAULT_SOURCES) -> list[dict]:
    return _load(path)


def add_source(name: str, url: str, type: str, *, path: Path = _DEFAULT_SOURCES) -> dict:
    if type not in _VALID_TYPES:
        raise ValueError(f"Invalid source type {type!r}; must be one of {_VALID_TYPES}")
    sources = _load(path)
    for s in sources:
        if s["url"] == url:
            return s
    base = _slugify(name)
    if not base:
        raise ValueError(
            f"Name {name!r} produces an empty slug; use at least one alphanumeric character"
        )
    existing_ids = {s["id"] for s in sources}
    sid = base
    n = 1
    while sid in existing_ids:
        sid = f"{base}-{n}"
        n += 1
    source = {"id": sid, "name": name, "url": url, "type": type, "active": True}
    sources.append(source)
    _save(path, sources)
    return source


def remove_source(id: str, *, path: Path = _DEFAULT_SOURCES) -> None:
    sources = _load(path)
    filtered = [s for s in sources if s["id"] != id]
    if len(filtered) == len(sources):
        raise KeyError(id)
    _save(path, filtered)


def toggle_source(id: str, *, path: Path = _DEFAULT_SOURCES) -> dict:
    sources = _load(path)
    for source in sources:
        if source["id"] == id:
            source["active"] = not source["active"]
            _save(path, sources)
            return source
    raise KeyError(id)
