from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response

from devforge.platform.monitor import monitor

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

BASE = Path(__file__).parent

HTML = BASE / "dashboard.html"
JS = BASE / "dashboard.js"
CSS = BASE / "dashboard.css"


# ------------------------------------------------------------
# UI
# ------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
def dashboard():
    return HTML.read_text()


@router.get("/app.js")
def js():
    return Response(JS.read_text(), media_type="application/javascript")


@router.get("/style.css")
def css():
    return Response(CSS.read_text(), media_type="text/css")


# ------------------------------------------------------------
# API
# ------------------------------------------------------------


@router.get("/api/status")
def status():
    return {
        "success_rate": monitor.get_success_rate(),
        "llm": monitor.get_llm_performance(),
    }


@router.get("/api/traces")
def traces(limit: int = 25):
    return monitor.get_recent_traces(limit=limit)


@router.get("/api/errors")
def errors(limit: int = 50):
    return monitor.get_events_by_severity("error", limit=limit)
