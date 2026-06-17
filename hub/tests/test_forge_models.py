"""Tests for forge_models — GGUF fit math, aliases, templates, overrides, plan_apply."""

import json
import struct
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from forge_models import (
    fit,
    detect,
    plan_apply,
    ModelError,
    GIB,
    OVERHEAD,
    RESERVE,
    FIT_SAFETY_MARGIN,
    KV_BYTES_PER_EL,
    CTX_CANDIDATES,
)


# ── Synthetic GGUF header builder ────────────────────────────────


def _build_gguf_header(metadata: dict) -> bytes:
    """Build a minimal valid GGUF header with the given metadata key/values.

    Supports only scalar types (int, float, bool) and short strings.
    This is enough to fool detect() without needing real tensors.
    """
    buf = bytearray()
    buf.extend(b"GGUF")
    buf.extend(struct.pack("<I", 3))  # version 3
    buf.extend(struct.pack("<Q", len(metadata)))  # n_tensors = 0
    buf.extend(struct.pack("<Q", len(metadata)))  # n_kv

    for key, value in metadata.items():
        key_bytes = key.encode("utf-8")
        buf.extend(struct.pack("<Q", len(key_bytes)))
        buf.extend(key_bytes)

        if isinstance(value, bool):
            buf.extend(struct.pack("<I", 7))  # BOOL
            buf.extend(struct.pack("<B", 1 if value else 0))
        elif isinstance(value, int):
            buf.extend(struct.pack("<I", 4))  # INT32
            buf.extend(struct.pack("<i", value))
        elif isinstance(value, float):
            buf.extend(struct.pack("<I", 12))  # FLOAT64
            buf.extend(struct.pack("<d", value))
        elif isinstance(value, str):
            val_bytes = value.encode("utf-8")
            buf.extend(struct.pack("<I", 8))  # STRING
            buf.extend(struct.pack("<Q", len(val_bytes)))
            buf.extend(val_bytes)
        else:
            raise TypeError(f"unsupported metadata type: {type(value)}")
    return bytes(buf)


# ── Fit tests ────────────────────────────────────────────────────


class TestFit:
    """VRAM fit estimation — these test the math, not real GGUF files."""

    def test_small_model_fits_comfortably(self):
        """A tiny model in a big VRAM budget."""
        d = {"size_bytes": 1 * GIB, "kv_per_tok": 100_000, "ctx_train": 32768}
        result = fit(d, vram=32 * GIB)
        assert result["status"] == "fits"
        assert result["ctx"] == 32768  # largest candidate

    def test_medium_model_fits_tight(self):
        """A model that fits but with little headroom."""
        # 12 GB model, kv_per_tok such that 16k ctx uses 4 GB → 16 GB total
        # Budget: 16 - 0.4 (RESERVE) - 0.6 (safety) = 15 GB
        # With 12 GB + 0.8 overhead + kv, ctx 16384 needs to fit in 15 GB
        d = {"size_bytes": 10 * GIB, "kv_per_tok": 100_000, "ctx_train": 32768}
        result = fit(d, vram=16 * GIB)
        # Should at least find some ctx
        assert result["ctx"] > 0
        assert result["status"] in ("fits", "tight")

    def test_oversized_model_spills(self):
        """A model too big for VRAM reports spills."""
        d = {"size_bytes": 30 * GIB, "kv_per_tok": 1_000_000, "ctx_train": 32768}
        result = fit(d, vram=16 * GIB)
        assert result["status"] == "spills"

    def test_ctx_cannot_exceed_trained(self):
        """Context must not exceed the model's trained context length."""
        d = {"size_bytes": 1 * GIB, "kv_per_tok": 10_000, "ctx_train": 8192}
        result = fit(d, vram=32 * GIB)
        assert result["ctx"] <= 8192

    def test_safety_margin_is_applied(self):
        """FIT_SAFETY_MARGIN should be subtracted from the budget."""
        d = {"size_bytes": 1 * GIB, "kv_per_tok": 10_000, "ctx_train": 32768}
        vram = 4 * GIB
        result = fit(d, vram=vram)
        budget = vram - RESERVE - FIT_SAFETY_MARGIN
        need = d["size_bytes"] + OVERHEAD + d["kv_per_tok"] * result["ctx"]
        assert need <= budget

    def test_need_gb_is_reasonable(self):
        """need_gb should be > size_bytes/GIB."""
        d = {"size_bytes": 10 * GIB, "kv_per_tok": 500_000, "ctx_train": 32768}
        result = fit(d, vram=32 * GIB)
        assert result["need_gb"] > d["size_bytes"] / GIB
        assert result["need_gb"] < 32  # must fit in VRAM


# ── detect tests (synthetic GGUF headers) ────────────────────────


class TestDetect:
    def test_basic_detection(self):
        """A minimal valid GGUF should produce a detect dict with required keys."""
        meta = {
            "general.architecture": "gemma",
            "general.basename": "test-model",
            "general.size_label": "12B",
            "general.finetune": "instruct",
            "gemma.context_length": 32768,
            "gemma.block_count": 40,
            "gemma.embedding_length": 4096,
            "gemma.attention.head_count": 32,
            "gemma.attention.head_count_kv": 8,
            "gemma.attention.key_length": 128,
            "gemma.expert_count": 0,
        }
        header = _build_gguf_header(meta)
        tmp = Path(tempfile.mktemp(suffix=".gguf"))
        tmp.write_bytes(header)
        try:
            d = detect(tmp)
            assert d["arch"] == "gemma"
            assert d["template"] == "gemma"
            assert d["template_known"] is True
            assert d["ctx_train"] == 32768
            assert d["moe"] is False
            assert d["extra_args"] == "--swa-full"
            assert d["size_bytes"] > 0
        finally:
            tmp.unlink()

    def test_moe_detection(self):
        """MoE models should have moe=True."""
        meta = {
            "general.architecture": "qwen",
            "general.basename": "moe-model",
            "general.size_label": "14B",
            "qwen.context_length": 32768,
            "qwen.block_count": 40,
            "qwen.embedding_length": 4096,
            "qwen.attention.head_count": 32,
            "qwen.attention.head_count_kv": 4,
            "qwen.attention.key_length": 128,
            "qwen.expert_count": 8,
        }
        header = _build_gguf_header(meta)
        tmp = Path(tempfile.mktemp(suffix=".gguf"))
        tmp.write_bytes(header)
        try:
            d = detect(tmp)
            assert d["moe"] is True
            assert d["arch"] == "qwen"
            assert d["template"] == "chatml"
        finally:
            tmp.unlink()

    def test_unknown_arch_defaults_to_chatml(self):
        """Unknown architectures should get template='chatml' and template_known=False."""
        meta = {
            "general.architecture": "mystery",
            "general.basename": "unknown-model",
            "mystery.context_length": 8192,
            "mystery.block_count": 24,
            "mystery.embedding_length": 2048,
            "mystery.attention.head_count": 16,
            "mystery.attention.head_count_kv": 4,
            "mystery.attention.key_length": 64,
        }
        header = _build_gguf_header(meta)
        tmp = Path(tempfile.mktemp(suffix=".gguf"))
        tmp.write_bytes(header)
        try:
            d = detect(tmp)
            assert d["template"] == "chatml"
            assert d["template_known"] is False
        finally:
            tmp.unlink()

    def test_alias_uniqueness_slug(self):
        """Alias should be a cleaned slug, not raw basename."""
        meta = {
            "general.architecture": "gemma",
            "general.basename": "My Cool Model! (v2)",
            "gemma.context_length": 32768,
            "gemma.block_count": 40,
            "gemma.embedding_length": 4096,
            "gemma.attention.head_count": 32,
            "gemma.attention.head_count_kv": 8,
            "gemma.attention.key_length": 128,
        }
        header = _build_gguf_header(meta)
        tmp = Path(tempfile.mktemp(suffix=".gguf"))
        tmp.write_bytes(header)
        try:
            d = detect(tmp)
            assert d["alias"].startswith("my-cool-model")
            # No uppercase, no special chars
            assert d["alias"] == d["alias"].lower()
            assert "(" not in d["alias"]
        finally:
            tmp.unlink()


# ── plan_apply tests ─────────────────────────────────────────────


class TestPlanApply:
    def test_missing_base_args(self):
        """plan_apply should error when LLAMA_BASE_ARGS is missing."""
        with patch("forge_models.read_env") as mock_read, patch("forge_models.scan") as mock_scan:
            mock_read.return_value = {}
            mock_scan.return_value = [
                {
                    "file": "test.gguf",
                    "alias": "test",
                    "path": "/tmp/test.gguf",
                    "arch": "gemma",
                    "template": "gemma",
                    "template_known": True,
                    "size_bytes": 10 * GIB,
                    "moe": False,
                    "extra_args": "",
                    "fit": {"status": "fits", "ctx": 16384, "need_gb": 10.0},
                    "sampling_hint": {},
                }
            ]
            plan = plan_apply("test")
            assert "error" in plan

    def test_missing_safety_cap(self):
        """plan_apply should refuse when --n-predict is missing from base args."""
        with patch("forge_models.read_env") as mock_read, patch("forge_models.scan") as mock_scan:
            mock_read.return_value = {"LLAMA_BASE_ARGS": "--host 0.0.0.0"}
            mock_scan.return_value = [
                {
                    "file": "test.gguf",
                    "alias": "test",
                    "path": "/tmp/test.gguf",
                    "arch": "gemma",
                    "template": "gemma",
                    "template_known": True,
                    "size_bytes": 10 * GIB,
                    "moe": False,
                    "extra_args": "",
                    "fit": {"status": "fits", "ctx": 16384, "need_gb": 10.0},
                    "sampling_hint": {},
                }
            ]
            plan = plan_apply("test")
            assert "error" in plan

    def test_successful_plan(self):
        """A successful plan_apply returns env_changes and model info."""
        with (
            patch("forge_models.read_env") as mock_read,
            patch("forge_models.scan") as mock_scan,
            patch("forge_models.plan_env") as mock_plan_env,
        ):
            mock_read.return_value = {
                "LLAMA_BASE_ARGS": "--host 0.0.0.0 --n-predict 4096",
                "LLAMA_ARGS": '"--host 0.0.0.0 --n-predict 4096 --ctx-size 8192"',
                "DEVFORGE_PROMPT_TEMPLATE": "gemma",
            }
            mock_scan.return_value = [
                {
                    "file": "test.gguf",
                    "alias": "test",
                    "path": "/tmp/test.gguf",
                    "arch": "gemma",
                    "template": "gemma",
                    "template_known": True,
                    "size_bytes": 10 * GIB,
                    "moe": False,
                    "extra_args": "--swa-full",
                    "fit": {"status": "fits", "ctx": 16384, "need_gb": 12.0},
                    "sampling_hint": {},
                }
            ]
            mock_plan_env.return_value = {"changes": {}, "new_keys": []}

            plan = plan_apply("test")
            assert "error" not in plan
            assert plan["model"]["alias"] == "test"
            assert plan["model"]["template"] == "gemma"
            assert "env_changes" in plan
            assert plan["devforge_restart"] in ("0", "1")

    def test_spills_warning(self):
        """A model that spills should produce a fit_warning."""
        with (
            patch("forge_models.read_env") as mock_read,
            patch("forge_models.scan") as mock_scan,
            patch("forge_models.plan_env") as mock_plan_env,
        ):
            mock_read.return_value = {
                "LLAMA_BASE_ARGS": "--host 0.0.0.0 --n-predict 4096",
            }
            mock_scan.return_value = [
                {
                    "file": "big.gguf",
                    "alias": "big",
                    "path": "/tmp/big.gguf",
                    "arch": "gemma",
                    "template": "gemma",
                    "template_known": True,
                    "size_bytes": 20 * GIB,
                    "moe": False,
                    "extra_args": "",
                    "fit": {"status": "spills", "ctx": 32768, "need_gb": 22.0},
                    "sampling_hint": {},
                }
            ]
            mock_plan_env.return_value = {"changes": {}, "new_keys": []}

            plan = plan_apply("big")
            assert plan.get("fit_warning") is not None
            assert "spill" in plan["fit_warning"]


# ── Regression: the --swa-full"" double-quote bug (June 13) ──────────
# write_env re-applies the original quote style of LLAMA_ARGS, so the
# value passed in must be RAW. plan_apply/compute_apply once passed a
# pre-quoted value, producing `""...--swa-full""` on disk → llama
# rejected it as an invalid argument and every swap failed + rolled back.


def _seed_stack_env(tmp_path):
    p = tmp_path / "stack.env"
    p.write_text(
        "LLAMA_BIN=/x/llama-server\n"
        "MODEL=/m/old.gguf\n"
        "MODEL_ALIAS=old\n"
        "LLAMA_PORT=8002\n"
        'LLAMA_BASE_ARGS="--host 0.0.0.0 --n-predict 4096"\n'
        'LLAMA_ARGS="--host 0.0.0.0 --n-predict 4096 --ctx-size 8192"\n'
        "DEVFORGE_PROMPT_TEMPLATE=gemma\n"
    )
    return p


def test_llama_args_roundtrip_no_double_quotes(tmp_path, monkeypatch):
    """After a swap writes LLAMA_ARGS, reading it back must yield a clean
    arg string with no embedded quote characters."""
    import forge_models as fm
    from forge_env import read_env, write_env

    envfile = _seed_stack_env(tmp_path)
    monkeypatch.setattr(fm, "ENVFILE", envfile)

    # Simulate what plan_apply returns for the args, then persist it the way
    # both compute_apply and the hub's swap_model do.
    base = read_env(envfile)["LLAMA_BASE_ARGS"]
    args = f"{base} --ctx-size 16384 --swa-full"
    write_env(envfile, {"LLAMA_ARGS": args})  # RAW value, as fixed

    written = envfile.read_text()
    assert '--swa-full""' not in written, "double-quote bug reintroduced"
    assert '""' not in written, f"stray double quotes in: {written!r}"

    parsed = read_env(envfile)["LLAMA_ARGS"]
    assert parsed.endswith("--swa-full")
    assert '"' not in parsed, f"quote leaked into parsed value: {parsed!r}"
    # exactly one surrounding quote pair on the line
    line = [l for l in written.splitlines() if l.startswith("LLAMA_ARGS=")][0]
    assert line == f'LLAMA_ARGS="{args}"', line


# ── KV-cache-aware fit (June 13): q4_0 cache halves KV, must not be
# over-counted (else a fitting context is wrongly called "spills" and the
# hub swap pre-flight falsely refuses it). ──
def test_kv_scale_from_args():
    import forge_models as fm

    assert fm.kv_scale_from_args("--cache-type-k q4_0 --cache-type-v q4_0") == 0.53
    assert fm.kv_scale_from_args("--cache-type-k q8_0") == 1.0
    assert fm.kv_scale_from_args("--cache-type-k f16") == 2.0
    assert fm.kv_scale_from_args("--ngl 99") == 1.0  # unspecified → baseline


def test_fit_q4_cache_doubles_context():
    import forge_models as fm

    # a model that fits 8k at q8 should fit ~16k at q4 (half the KV cost)
    d = {"size_bytes": int(12.4 * fm.GIB), "kv_per_tok": 122716, "ctx_train": 32768}
    vram = 16368 * 1024 * 1024
    q8 = fm.fit(d, vram, kv_scale=1.0)
    q4 = fm.fit(d, vram, kv_scale=0.53)
    assert q4["ctx"] >= q8["ctx"] * 2, f"q4 should ~double ctx: q8={q8['ctx']} q4={q4['ctx']}"
    assert q4["status"] in ("fits", "tight")
