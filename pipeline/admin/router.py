import json
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from pipeline.auth import get_auth_status
from pipeline.sources import add_source, list_sources, remove_source, toggle_source

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _read_last_run(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    last_run = _read_last_run(request.app.state.last_run_path)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"last_run": last_run, "auth": get_auth_status()},
    )


@router.get("/sources", response_class=HTMLResponse)
async def sources_page(request: Request):
    sources = list_sources(request.app.state.sources_path)
    return templates.TemplateResponse(request, "sources.html", {"sources": sources})


@router.post("/sources")
async def add_source_route(
    request: Request,
    name: str = Form(...),
    url: str = Form(...),
    type: str = Form(...),
):
    add_source(name, url, type, path=request.app.state.sources_path)
    return RedirectResponse(url="/admin/sources", status_code=303)


@router.delete("/sources/{id}", status_code=204)
async def delete_source_route(id: str, request: Request):
    try:
        remove_source(id, path=request.app.state.sources_path)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Source {id!r} not found")


@router.patch("/sources/{id}")
async def toggle_source_route(id: str, request: Request):
    try:
        source = toggle_source(id, path=request.app.state.sources_path)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Source {id!r} not found")
    return JSONResponse(source)


@router.get("/feedback", response_class=HTMLResponse)
async def feedback_page(request: Request):
    return templates.TemplateResponse(request, "feedback.html")
