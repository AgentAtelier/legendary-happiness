"""Tests for the hub's FastAPI endpoints — guards, job lifecycle, 409-when-busy."""

import pytest
from fastapi.testclient import TestClient

from hub import _jobs, app

client = TestClient(app)


# ── Origin guard tests ────────────────────────────────────────────


class TestOriginGuard:
    def test_allowed_host(self):
        """Request from 127.0.0.1:8003 should pass."""
        r = client.get("/api/status", headers={"Host": "127.0.0.1:8003"})
        assert r.status_code == 200

    def test_allowed_localhost(self):
        r = client.get("/api/status", headers={"Host": "localhost:8003"})
        assert r.status_code == 200

    def test_forbidden_host(self):
        """Request from an external host should get 403."""
        r = client.get("/api/status", headers={"Host": "evil.com:8003"})
        assert r.status_code == 403

    def test_csrf_header_required_on_post(self):
        """POST without the custom CSRF header should get 403."""
        r = client.post("/api/run", headers={"Host": "127.0.0.1:8003"}, json={"action": "doctor"})
        assert r.status_code == 403

    def test_csrf_header_present_post_passes(self):
        """POST with the CSRF header should pass the guard (may still fail validation)."""
        r = client.post("/api/run", headers={"Host": "127.0.0.1:8003", "X-Forge-Hub": "1"}, json={"action": "doctor"})
        # 409 means guard passed, job system kicked in
        assert r.status_code in (200, 409)

    def test_get_no_csrf_needed(self):
        """GET requests don't need the CSRF header."""
        r = client.get("/api/status", headers={"Host": "localhost:8003"})
        assert r.status_code == 200


# ── Endpoint tests ────────────────────────────────────────────────


class TestEndpoints:
    def test_index_returns_html(self):
        r = client.get("/", headers={"Host": "127.0.0.1:8003"})
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")

    def test_status_returns_json(self):
        r = client.get("/api/status", headers={"Host": "127.0.0.1:8003"})
        assert r.status_code == 200
        data = r.json()
        assert "chips" in data
        assert "model" in data
        assert "alias" in data
        assert "template" in data
        assert "busy" in data

    def test_config_get(self):
        r = client.get("/api/config", headers={"Host": "127.0.0.1:8003"})
        # May 500 if stack.env missing, but should be a valid response code
        assert r.status_code in (200, 500)

    def test_models_endpoint(self):
        r = client.get("/api/models", headers={"Host": "127.0.0.1:8003"})
        # May fail if forge-model not available, but shouldn't 403
        assert r.status_code != 403

    def test_logs_unknown_service(self):
        r = client.get("/api/logs/bogus?n=50", headers={"Host": "127.0.0.1:8003"})
        assert r.status_code == 400

    def test_doc_endpoint(self):
        r = client.get("/api/doc", headers={"Host": "127.0.0.1:8003"})
        assert r.status_code == 200

    def test_bench_tests(self):
        r = client.get("/api/bench/tests", headers={"Host": "127.0.0.1:8003"})
        assert r.status_code == 200
        data = r.json()
        assert "tests" in data
        assert "bundles" in data

    def test_bench_history(self):
        r = client.get("/api/bench/history", headers={"Host": "127.0.0.1:8003"})
        assert r.status_code == 200


# ── Run endpoint tests ────────────────────────────────────────────


class TestRunEndpoint:
    def test_unknown_action(self):
        r = client.post(
            "/api/run", headers={"Host": "127.0.0.1:8003", "X-Forge-Hub": "1"}, json={"action": "fly-to-moon"}
        )
        assert r.status_code == 400

    def test_missing_action(self):
        r = client.post("/api/run", headers={"Host": "127.0.0.1:8003", "X-Forge-Hub": "1"}, json={})
        assert r.status_code == 400

    def test_model_action_no_arg(self):
        """model action without arg should 400."""
        r = client.post("/api/run", headers={"Host": "127.0.0.1:8003", "X-Forge-Hub": "1"}, json={"action": "model"})
        assert r.status_code == 400

    def test_model_action_bad_arg(self):
        """model action with invalid fragment should 400."""
        r = client.post(
            "/api/run",
            headers={"Host": "127.0.0.1:8003", "X-Forge-Hub": "1"},
            json={"action": "model", "arg": "../../etc/passwd"},
        )
        assert r.status_code == 400

    def test_known_action_returns_job_id(self):
        """A known read-only action should return a job ID."""
        r = client.post("/api/run", headers={"Host": "127.0.0.1:8003", "X-Forge-Hub": "1"}, json={"action": "doctor"})
        # 200 means job accepted; 409 means another job already running
        assert r.status_code in (200, 409)
        if r.status_code == 200:
            data = r.json()
            assert "job" in data
            assert len(data["job"]) == 12  # uuid4 hex[:12]


class TestStreamEndpoint:
    def test_nonexistent_job_404(self):
        r = client.get("/api/stream/deadbeef1234", headers={"Host": "127.0.0.1:8003"})
        assert r.status_code == 404

    def test_existing_job_streams(self):
        """Create a fake job and verify the stream endpoint finds it."""
        job_id = "test12345678"
        _jobs[job_id] = {
            "lines": ["test line"],
            "done": True,
            "exit": 0,
            "t": 9999999999,
        }
        try:
            r = client.get(f"/api/stream/{job_id}", headers={"Host": "127.0.0.1:8003"})
            assert r.status_code == 200
            assert "text/event-stream" in r.headers.get("content-type", "")
        finally:
            _jobs.pop(job_id, None)


class TestSwapEndpoint:
    def test_missing_fragment(self):
        r = client.post("/api/swap", headers={"Host": "127.0.0.1:8003", "X-Forge-Hub": "1"}, json={})
        assert r.status_code == 400

    def test_invalid_fragment(self):
        r = client.post(
            "/api/swap", headers={"Host": "127.0.0.1:8003", "X-Forge-Hub": "1"}, json={"fragment": "../../etc/passwd"}
        )
        assert r.status_code == 400

    @pytest.mark.skip(reason="dispatches live swap against the real stack — use -m live to include")
    def test_valid_fragment_returns_job_id(self):
        """A valid fragment should return a job_id (or 409 if busy).

        SKIPPED by default: this test triggers a real model swap via the
        swap endpoint, which restarts llama and mutates the running stack.
        Run with -m live when the full stack is up.
        """
        r = client.post(
            "/api/swap", headers={"Host": "127.0.0.1:8003", "X-Forge-Hub": "1"}, json={"fragment": "test-model"}
        )
        assert r.status_code in (200, 409)

    def test_csrf_required(self):
        r = client.post("/api/swap", headers={"Host": "127.0.0.1:8003"}, json={"fragment": "test"})
        assert r.status_code == 403


class TestConfigSave:
    def test_empty_body(self):
        r = client.post("/api/config", headers={"Host": "127.0.0.1:8003", "X-Forge-Hub": "1"}, json={"text": ""})
        assert r.status_code == 400

    def test_not_a_stack_env(self):
        """Saving something that doesn't look like stack.env should 400."""
        r = client.post(
            "/api/config", headers={"Host": "127.0.0.1:8003", "X-Forge-Hub": "1"}, json={"text": "hello world"}
        )
        assert r.status_code == 400


class TestNewEndpoints:
    """Phase 4+5+6: new hub endpoints."""

    def test_version_endpoint(self):
        r = client.get("/api/version", headers={"Host": "127.0.0.1:8003"})
        assert r.status_code == 200
        data = r.json()
        assert "build" in data
        assert len(data["build"]) == 12

    def test_selfcheck_endpoint(self):
        r = client.get("/api/selfcheck", headers={"Host": "127.0.0.1:8003"})
        assert r.status_code == 200
        data = r.json()
        assert "build" in data
        assert "expected_fields" in data
        assert "status" in data["expected_fields"]
        assert "models" in data["expected_fields"]

    def test_actions_endpoint(self):
        r = client.get("/api/actions?n=5", headers={"Host": "127.0.0.1:8003"})
        assert r.status_code == 200
        data = r.json()
        assert "actions" in data
        assert isinstance(data["actions"], list)

    def test_config_backups_endpoint(self):
        r = client.get("/api/config/backups", headers={"Host": "127.0.0.1:8003"})
        assert r.status_code == 200
        data = r.json()
        assert "backups" in data


class TestConfigSaveValidation:
    """Phase 6: config save uses schema validator."""

    def test_invalid_config_rejected(self):
        """Saving something that fails schema validation should 400."""
        r = client.post(
            "/api/config",
            headers={"Host": "127.0.0.1:8003", "X-Forge-Hub": "1"},
            json={"text": "just some random text\nnot a valid config"},
        )
        assert r.status_code == 400

    def test_empty_config_rejected(self):
        r = client.post("/api/config", headers={"Host": "127.0.0.1:8003", "X-Forge-Hub": "1"}, json={"text": ""})
        assert r.status_code == 400

    def test_config_no_csrf_rejected(self):
        r = client.post("/api/config/restore", headers={"Host": "127.0.0.1:8003"})
        assert r.status_code == 403


class TestScenarioEndpoints:
    """Stream A: scenario + scorecard API tests."""

    def test_scenarios_list(self):
        r = client.get("/api/scenarios", headers={"Host": "127.0.0.1:8003"})
        assert r.status_code == 200
        data = r.json()
        assert "scenarios" in data
        assert len(data["scenarios"]) >= 10
        # Each scenario has required fields
        for s in data["scenarios"]:
            assert "id" in s
            assert "prompt" in s
            assert "category" in s
            assert "assertions" in s
            assert "cleanup" in s
        assert "tool_call_probes" in data

    def test_scenarios_list_tool_probes(self):
        r = client.get("/api/scenarios", headers={"Host": "127.0.0.1:8003"})
        data = r.json()
        probes = data["tool_call_probes"]
        assert len(probes) >= 4
        ids = [p["id"] for p in probes]
        assert "tool_scene_hierarchy" in ids
        assert "tool_create_cube" in ids
        assert "tool_none" in ids

    def test_scenarios_run_requires_ids(self):
        r = client.post("/api/scenarios/run", json={"ids": []}, headers={"Host": "127.0.0.1:8003", "x-forge-hub": "1"})
        assert r.status_code == 400

    @pytest.mark.skip(reason="triggers live DevForge apply_spec — use only with stack running")
    def test_scenarios_run_returns_job(self):
        r = client.post(
            "/api/scenarios/run",
            json={"ids": ["no_dup_camera"]},
            headers={"Host": "127.0.0.1:8003", "x-forge-hub": "1"},
        )
        assert r.status_code == 200
        data = r.json()
        assert "job" in data

    def test_scorecards_list(self):
        r = client.get("/api/scorecards", headers={"Host": "127.0.0.1:8003"})
        assert r.status_code == 200
        data = r.json()
        assert "scorecards" in data
        assert isinstance(data["scorecards"], list)

    def test_scorecards_compare_requires_params(self):
        r = client.get("/api/scorecards/compare", headers={"Host": "127.0.0.1:8003"})
        assert r.status_code == 400

    def test_scorecards_compare_with_params(self):
        r = client.get("/api/scorecards/compare?model_a=gemma&model_b=qwen", headers={"Host": "127.0.0.1:8003"})
        assert r.status_code == 200
        data = r.json()
        # May have error if no scorecards, which is fine
        assert "model_a" in data or "error" in data


# ── Rework: theme, logo, nav, testing tab, feedback ───────────────


class TestTheme:
    def test_new_palette_tokens_served(self):
        r = client.get("/", headers={"Host": "127.0.0.1:8003"})
        assert r.status_code == 200
        html = r.text
        # middle-ground palette + bright border
        assert "--bg:#0a0e0a" in html
        assert "--panebg:#0e160e" in html
        assert "--fg:#b8e6c4" in html
        assert "--border:#3f9657" in html
        assert "--warn-amber:#e0b341" in html


class TestLogo:
    def test_logo_svg_present(self):
        html = client.get("/", headers={"Host": "127.0.0.1:8003"}).text
        assert 'id="forge-logo"' in html
        assert "<svg" in html
        assert 'aria-label="Forge Hub logo"' in html


class TestNormalizedShape:
    def test_normalize_contract(self):
        """The canonical normalizer the frontend mirrors must yield the keys the
        Testing tab's renderScorecard depends on."""
        from forge_score import normalize_result

        card = normalize_result(
            "gauntlet", {"coverage": 83, "metrics": {"nodes": "3/25"}}, target="current", label="G7"
        )
        assert set(card) >= {"suite", "target", "label", "score", "verdict", "metrics"}
        assert card["verdict"] in ("pass", "partial", "fail")


class TestNav:
    def test_six_tab_nav(self):
        html = client.get("/", headers={"Host": "127.0.0.1:8003"}).text
        assert 'data-tab="testing"' in html
        # old testing tabs folded out of the nav (precise to nav <button> markup;
        # dormant JS string refs to old tabs are removed in Task 11 cleanup)
        for gone in (
            '<button data-tab="bench"',
            '<button data-tab="score"',
            '<button data-tab="shootout"',
            '<button data-tab="gauntlet"',
        ):
            assert gone not in html, f"{gone} should be removed from nav"
        # survivors
        for keep in ("overview", "testing", "models", "config", "activity", "doc"):
            assert f'data-tab="{keep}"' in html

    def test_testing_tab_body_present(self):
        html = client.get("/", headers={"Host": "127.0.0.1:8003"}).text
        assert 'id="tab-testing"' in html
        assert 'id="testing-rail"' in html
        assert 'id="testing-results"' in html


class TestTestingRunner:
    """The rail + results are JS-injected; assert the building code is served."""

    def test_facet_controls_in_source(self):
        html = client.get("/", headers={"Host": "127.0.0.1:8003"}).text
        assert 'id="facet-target"' in html
        assert 'id="facet-suite"' in html
        assert 'id="facet-depth"' in html
        assert 'id="testing-run"' in html

    def test_results_scaffold_in_source(self):
        html = client.get("/", headers={"Host": "127.0.0.1:8003"}).text
        assert 'id="status-strip"' in html
        assert 'id="scorecard-host"' in html
        assert 'id="testing-history"' in html

    def test_runner_functions_in_source(self):
        html = client.get("/", headers={"Host": "127.0.0.1:8003"}).text
        assert "function runTesting" in html
        assert "function renderScorecard" in html
        assert "function initTesting" in html


class TestButtonFeedback:
    def test_helpers_present(self):
        html = client.get("/", headers={"Host": "127.0.0.1:8003"}).text
        assert "function buttonBusy" in html
        assert "function buttonFlash" in html
        assert "function toast" in html
