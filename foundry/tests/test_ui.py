"""TDD tests for foundry.ui MVP — FastAPI TestClient with injected fakes.

No llama.cpp, no Blender — the forge pipeline is fully faked.
Tests cover:
  - POST /forge returns job_id
  - GET /jobs/{id} reaches "done" state
  - GET /decisions renders injected Decision Points
  - GET /report returns 404 when not configured
  - POST /rerun at each layer
"""

from __future__ import annotations

import json
import threading

import pytest
from fastapi.testclient import TestClient

# ── Fake forge pipeline ───────────────────────────────────────────────


def _fake_plan(request: str):
    """Fake planner — returns a deterministic spec."""
    from decisions import Choice, make_decision
    spec = {
        "asset_id": "table",
        "generator": "table",
        "material": "worn_oak",
        "age": 0.15,
        "params": {
            "top_width": 1.2, "top_depth": 0.8, "top_thickness": 0.06,
            "leg_height": 0.65, "leg_radius": 0.05, "leg_inset": 0.1,
        },
    }
    dp = make_decision(
        code="material.unspecified_defaulted",
        stage="planner",
        severity="assumption",
        context={"resolved": "worn_oak"},
        choices=(Choice(label="Wrought Iron", plain="dark tinted metal",
                       apply={"field": "material", "value": "wrought_iron"}),),
    )
    return spec, [dp]


def _fake_forge(spec: dict, decisions: list, library_dir: str) -> dict:
    """Fake forge — returns a result without running Blender."""
    return {
        "glb_path": f"{library_dir}/table_worn_oak.glb",
        "gate_passed": True,
        "registered": True,
    }


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Create a TestClient wired with the fake forge pipeline.

    Forge jobs run on a daemon background thread in production, but the
    fakes are instant — replacing ``Thread.start`` with a synchronous
    ``Thread.run`` lets the POST /forge call return *after* the job
    completes, so test assertions can read state directly with no
    ``time.sleep`` and no poll loop (P21 audit).
    """
    from ui.app import app, configure_forge

    def _sync_start(self: threading.Thread) -> None:
        # Run the target inline so the background job finishes before
        # POST /forge returns; tests assert on state immediately.
        self.run()

    monkeypatch.setattr(threading.Thread, "start", _sync_start)

    # Reset app-level injectables between tests
    configure_forge(
        plan_fn=_fake_plan,
        forge_fn=_fake_forge,
        library_dir=str(tmp_path / "library"),
        report_path="",
    )
    with TestClient(app) as c:
        yield c


# ── /forge + /jobs ────────────────────────────────────────────────────


def test_forge_returns_job_id(client):
    """POST /forge returns a job_id."""
    r = client.post("/forge", json={"request": "a table"})
    assert r.status_code == 200
    data = r.json()
    assert "job_id" in data
    assert len(data["job_id"]) == 8


def test_forge_missing_request_returns_422(client):
    """POST /forge without a 'request' field → 422."""
    r = client.post("/forge", json={})
    assert r.status_code == 422


def test_forge_empty_request_returns_422(client):
    """POST /forge with empty 'request' → 422."""
    r = client.post("/forge", json={"request": "  "})
    assert r.status_code == 422


def test_job_poll_reaches_done(client):
    """POST /forge then GET /jobs/{id} → 'done'.

    The ``client`` fixture monkey-patches ``Thread.start`` to run
    synchronously, so the job has already completed by the time POST
    returns — we can read the state directly without polling.
    """
    r = client.post("/forge", json={"request": "an old table"})
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    r2 = client.get(f"/jobs/{job_id}")
    assert r2.status_code == 200
    result = r2.json()
    assert result["status"] == "done"
    assert result["result"]["glb_path"] != ""
    assert result["result"]["spec"]["material"] == "worn_oak"
    assert result["result"]["spec"]["age"] == 0.15


def test_job_not_found_returns_404(client):
    """GET /jobs/nonexistent → 404."""
    r = client.get("/jobs/nonexistent")
    assert r.status_code == 404


# ── /decisions ────────────────────────────────────────────────────────


def test_decisions_endpoint_returns_list(client):
    """GET /decisions returns a list under 'decisions' key."""
    r = client.get("/decisions")
    assert r.status_code == 200
    data = r.json()
    assert "decisions" in data
    assert isinstance(data["decisions"], list)


def test_decisions_populated_after_forge(client):
    """After a forge job completes, /decisions includes the fired decisions.

    The ``client`` fixture runs the background job synchronously, so
    the forge has already completed by the time we hit ``/decisions``.
    """
    r = client.post("/forge", json={"request": "a wooden table"})
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    # Confirm job is done (sync thread fixture makes this immediate).
    r2 = client.get(f"/jobs/{job_id}")
    assert r2.status_code == 200
    assert r2.json()["status"] == "done"

    r3 = client.get("/decisions")
    decisions = r3.json()["decisions"]
    assert len(decisions) >= 1
    # The fake plan always emits material.unspecified_defaulted
    codes = {d.get("code") for d in decisions}
    assert "material.unspecified_defaulted" in codes


# ── /report ───────────────────────────────────────────────────────────


def test_report_returns_404_when_not_configured(client):
    """GET /report → 404 when no report path is set."""
    r = client.get("/report")
    assert r.status_code == 404


def test_report_returns_json_when_configured(tmp_path):
    """GET /report returns report.json content when configured."""
    from ui.app import app, configure_forge

    # Write a fake report
    report_file = tmp_path / "report.json"
    report_file.write_text(json.dumps({"total": 10, "signal_counts": {"clean": 8}}))

    configure_forge(
        plan_fn=_fake_plan,
        forge_fn=_fake_forge,
        report_path=str(report_file),
    )
    with TestClient(app) as c:
        r = c.get("/report")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 10


# ── /rerun ────────────────────────────────────────────────────────────


def test_rerun_material_only(client):
    """POST /rerun with layer=material-only re-resolves material."""
    r = client.post("/rerun", json={
        "spec": {
            "request": "an iron table",
            "asset_id": "table",
            "generator": "table",
            "material": "worn_oak",
            "age": 0.15,
            "params": {"top_width": 1.2},
        },
        "layer": "material-only",
    })
    assert r.status_code == 200
    data = r.json()
    # Resolver should find "iron" → wrought_iron
    assert data["spec"]["material"] == "wrought_iron"


def test_rerun_full_prompt(client):
    """POST /rerun with layer=full-prompt calls the injected plan_fn."""
    r = client.post("/rerun", json={
        "spec": {
            "request": "a table",
            "asset_id": "table",
            "generator": "table",
            "material": "worn_oak",
            "age": 0.15,
            "params": {},
        },
        "layer": "full-prompt",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["spec"]["generator"] == "table"
    assert data["spec"]["material"] == "worn_oak"
    assert len(data["decisions"]) >= 1


def test_rerun_params_layer(client):
    """POST /rerun with layer=params keeps material/age."""
    r = client.post("/rerun", json={
        "spec": {
            "request": "a granite table",
            "asset_id": "table",
            "generator": "table",
            "material": "dark_walnut",  # will be kept (params-only)
            "age": 0.8,
            "params": {},
        },
        "layer": "params",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["spec"]["material"] == "dark_walnut"  # preserved
    assert data["spec"]["age"] == 0.8  # preserved from original spec


# ── Static / index ────────────────────────────────────────────────────


def test_index_returns_html(client):
    """GET / returns the index.html page."""
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Forge UI" in r.text


def test_static_serves_index(client):
    """GET /static/index.html serves the static file."""
    r = client.get("/static/index.html")
    assert r.status_code == 200
