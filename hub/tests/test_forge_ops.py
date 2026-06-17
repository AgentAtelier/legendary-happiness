"""Tests for forge_ops — transactional swap, VRAM check, rollback."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from forge_ops import (
    check_drift,
    reconcile_model,
    run_cmd_capture,
    swap_model,
)


class TestCheckDrift:
    @pytest.mark.asyncio
    async def test_llama_down_returns_none(self):
        """When llama is down, check_drift returns None."""
        with patch("forge_ops.read_env") as mock_read, patch("forge_ops.run_cmd_capture") as mock_cmd:
            mock_read.return_value = {"LLAMA_PORT": "8002"}
            mock_cmd.return_value = (0, "inactive")
            result = await check_drift()
            assert result is None

    @pytest.mark.asyncio
    async def test_no_drift(self):
        """When configured and running match, drift is False."""
        with patch("forge_ops.read_env") as mock_read, patch("forge_ops.run_cmd_capture") as mock_cmd:
            mock_read.return_value = {
                "LLAMA_PORT": "8002",
                "MODEL_ALIAS": "test-model",
                "LLAMA_ARGS": '"--ctx-size 4096"',
            }
            # systemctl is-active → active
            mock_cmd.return_value = (0, "active")

            # Mock httpx /props response
            with patch("forge_ops.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client_cls.return_value.__aenter__.return_value = mock_client
                props_resp = MagicMock()
                props_resp.status_code = 200
                props_resp.json.return_value = {
                    "model_alias": "test-model",
                    "n_ctx": 4096,
                }
                mock_client.get = AsyncMock(return_value=props_resp)

                result = await check_drift()
                assert result is not None
                assert result["drift"] is False
                assert result["running_alias"] == "test-model"

    @pytest.mark.asyncio
    async def test_drift_detected(self):
        """When configured and running differ, drift is True."""
        with patch("forge_ops.read_env") as mock_read, patch("forge_ops.run_cmd_capture") as mock_cmd:
            mock_read.return_value = {
                "LLAMA_PORT": "8002",
                "MODEL_ALIAS": "configured-model",
                "LLAMA_ARGS": '"--ctx-size 8192"',
            }
            mock_cmd.return_value = (0, "active")

            with patch("forge_ops.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client_cls.return_value.__aenter__.return_value = mock_client
                props_resp = MagicMock()
                props_resp.status_code = 200
                props_resp.json.return_value = {
                    "model_alias": "running-model",  # different!
                    "n_ctx": 4096,  # different!
                }
                mock_client.get = AsyncMock(return_value=props_resp)

                result = await check_drift()
                assert result is not None
                assert result["drift"] is True
                assert "configured-model" in (result.get("reason") or "")


class TestReconcile:
    @pytest.mark.asyncio
    async def test_reconcile_success(self):
        """reconcile_model should restart llama, poll /health, and verify."""
        lines: list[str] = []

        def emit(s: str) -> None:
            lines.append(s)

        with (
            patch("forge_ops.read_env", return_value={"LLAMA_PORT": "8002", "MODEL_ALIAS": "test"}),
            patch("forge_ops.run_cmd_capture", return_value=(0, "")),
            patch("forge_ops._service_is_failed", return_value=False),
        ):
            with patch("forge_ops.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client_cls.return_value.__aenter__.return_value = mock_client
                health_resp = MagicMock()
                health_resp.status_code = 200
                props_resp = MagicMock()
                props_resp.status_code = 200
                props_resp.json.return_value = {"model_alias": "test"}
                mock_client.get = AsyncMock(side_effect=[health_resp, props_resp])

                exit_code = await reconcile_model(emit)
                assert exit_code == 0
                assert any("reconciled" in l.lower() for l in lines)

    @pytest.mark.asyncio
    async def test_reconcile_returns_1_on_service_crash(self):
        """When llama crashes during reconcile, should return 1."""
        lines: list[str] = []

        def emit(s: str) -> None:
            lines.append(s)

        with (
            patch("forge_ops.read_env", return_value={"LLAMA_PORT": "8002", "MODEL_ALIAS": "test"}),
            patch("forge_ops.run_cmd_capture", return_value=(0, "")),
            patch("forge_ops._service_is_failed", return_value=True),
            patch("forge_ops.get_service_logs", return_value="segfault"),
        ):
            exit_code = await reconcile_model(emit)
            assert exit_code == 1
            assert any("crashed" in l.lower() for l in lines)


class TestGetFreeVRAM:
    @pytest.mark.asyncio
    async def test_simple_echo(self):
        code, out = await run_cmd_capture("echo", "hello")
        assert code == 0
        assert "hello" in out

    @pytest.mark.asyncio
    async def test_command_not_found(self):
        code, out = await run_cmd_capture("nonexistent_cmd_9238472")
        assert code != 0


class TestSwapModel:
    @pytest.mark.asyncio
    async def test_ambiguous_fragment(self):
        """An ambiguous fragment should return exit code 1 without touching config."""
        lines: list[str] = []

        def emit(s: str) -> None:
            lines.append(s)

        with patch("forge_ops.plan_apply") as mock_plan:
            from forge_models import ModelError

            mock_plan.side_effect = ModelError("ambiguous fragment")
            exit_code = await swap_model("ambig", emit)
            assert exit_code == 1
            assert any("error" in l.lower() for l in lines)

    @pytest.mark.asyncio
    async def test_vram_too_low(self):
        """When free VRAM is less than model needs, should refuse."""
        lines: list[str] = []

        def emit(s: str) -> None:
            lines.append(s)

        plan = {
            "model": {
                "path": "/tmp/test.gguf",
                "alias": "test-model",
                "template": "gemma",
                "fit": {"need_gb": 20.0, "ctx": 32768, "status": "spills"},
            },
            "llama_args": '"--host 0.0.0.0 --n-predict 4096 --ctx-size 32768"',
            "devforge_restart": "0",
        }

        with (
            patch("forge_ops.plan_apply", return_value=plan),
            patch("forge_ops.get_free_vram", return_value=8 * 1024**3),
        ):
            exit_code = await swap_model("big-model", emit)
            assert exit_code == 1
            assert any("vram" in l.lower() for l in lines)

    @pytest.mark.asyncio
    async def test_plan_error(self):
        """plan_apply returning an error dict should fail."""
        lines: list[str] = []

        def emit(s: str) -> None:
            lines.append(s)

        with patch("forge_ops.plan_apply", return_value={"error": "missing base args"}):
            exit_code = await swap_model("broken", emit)
            assert exit_code == 1

    @pytest.mark.asyncio
    async def test_rollback_on_service_crash(self):
        """When llama crashes during swap, config must be rolled back."""
        lines: list[str] = []

        def emit(s: str) -> None:
            lines.append(s)

        plan = {
            "model": {
                "path": "/tmp/test.gguf",
                "alias": "test-model",
                "template": "gemma",
                "fit": {"need_gb": 1.0, "ctx": 4096, "status": "fits"},
            },
            "llama_args": '"--host 0.0.0.0 --n-predict 4096 --ctx-size 4096"',
            "devforge_restart": "0",
        }

        with (
            patch("forge_ops.plan_apply", return_value=plan),
            patch("forge_ops.get_free_vram", return_value=16 * 1024**3),
            patch("forge_ops.read_env", return_value={"LLAMA_PORT": "8002"}),
            patch("forge_ops.write_env") as mock_write,
            patch("forge_ops.run_cmd_capture") as mock_cmd,
            patch("forge_ops._service_is_failed", return_value=True),
            patch("forge_ops.get_service_logs", return_value="cudaMalloc failed: out of memory"),
        ):
            mock_cmd.return_value = (0, "")

            exit_code = await swap_model("test-model", emit)
            assert exit_code == 1
            # Verify rollback was performed
            assert any("rollback" in l.lower() for l in lines)
            # Verify diagnostic was captured
            assert any("cudaMalloc" in l for l in lines)

    @pytest.mark.asyncio
    async def test_successful_swap(self):
        """Full happy path: plan, write, restart, health, props, verified."""
        lines: list[str] = []

        def emit(s: str) -> None:
            lines.append(s)

        plan = {
            "model": {
                "path": "/tmp/test.gguf",
                "alias": "test-model",
                "template": "gemma",
                "fit": {"need_gb": 1.0, "ctx": 4096, "status": "fits"},
            },
            "llama_args": '"--host 0.0.0.0 --n-predict 4096 --ctx-size 4096"',
            "devforge_restart": "0",
        }

        async def mock_cmd_side_effect(*args):
            # First call: systemctl restart → success
            # Second call: systemctl show → not failed
            return (0, "ActiveState=active\nSubState=running\n")

        mock_cmd = AsyncMock(side_effect=mock_cmd_side_effect)

        with (
            patch("forge_ops.plan_apply", return_value=plan),
            patch("forge_ops.get_free_vram", return_value=16 * 1024**3),
            patch("forge_ops.read_env", return_value={"LLAMA_PORT": "8002"}),
            patch("forge_ops.write_env") as mock_write,
            patch("forge_ops.run_cmd_capture", new=mock_cmd),
            patch("forge_ops._service_is_failed", return_value=False),
        ):
            # Mock httpx to return /health 200 and /props with correct alias
            with patch("forge_ops.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client_cls.return_value.__aenter__.return_value = mock_client

                health_resp = MagicMock()
                health_resp.status_code = 200
                props_resp = MagicMock()
                props_resp.status_code = 200
                props_resp.json.return_value = {"model_alias": "test-model"}

                mock_client.get = AsyncMock(side_effect=[health_resp, props_resp])

                exit_code = await swap_model("test-model", emit)
                assert exit_code == 0
                assert any("verified" in l.lower() for l in lines)


class TestClassifyFailure:
    """Phase 4: failure classifier tests."""

    def test_cuda_oom(self):
        from forge_ops import classify_failure

        r = classify_failure("cudaMalloc failed: out of memory")
        assert r["cause"] != "unknown"
        assert "VRAM" in r["cause"] or "big" in r["cause"].lower()

    def test_segfault(self):
        from forge_ops import classify_failure

        r = classify_failure("SIGSEGV: segmentation fault")
        assert r["cause"] != "unknown"
        assert "segfault" in r["cause"].lower() or "crash" in r["cause"].lower()

    def test_port_conflict(self):
        from forge_ops import classify_failure

        r = classify_failure("address already in use")
        assert r["cause"] != "unknown"
        assert "port" in r["cause"].lower()

    def test_unknown_error(self):
        from forge_ops import classify_failure

        r = classify_failure("something completely unexpected happened")
        assert r["cause"] == "unknown"

    def test_oom_killer(self):
        from forge_ops import classify_failure

        r = classify_failure("killed by OOM killer")
        assert r["cause"] != "unknown"
        assert "oom" in r["cause"].lower()


class TestActionLog:
    """Phase 4: durable action log tests."""

    def test_record_and_retrieve(self):
        from forge_ops import get_action_history, record_action

        # Record a test action
        record_action("test", ["test", "arg"], 0, 1.0, output="all good")
        # Should be retrievable
        history = get_action_history(5)
        assert len(history) > 0
        found = [h for h in history if h["action"] == "test"]
        assert len(found) > 0
        assert found[0]["exit_code"] == 0

    def test_failed_action_has_classification(self):
        from forge_ops import get_action_history, record_action

        record_action("test-fail", ["bad"], 1, 0.5, error="cudaMalloc failed: out of memory")
        history = get_action_history(5)
        found = [h for h in history if h["action"] == "test-fail"]
        assert len(found) > 0
        assert found[0]["exit_code"] == 1
        assert "classification" in found[0]
        assert found[0]["classification"]["cause"] != "unknown"
