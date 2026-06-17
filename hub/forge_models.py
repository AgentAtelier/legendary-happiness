"""
forge_models — shared model-intelligence library for the forge stack.

Used by BOTH the hub (hub.py) and the forge-model CLI so they can never
diverge on GGUF parsing, VRAM fit estimation, registry management, or
apply behavior. The forge-model CLI becomes a thin wrapper that only
handles argument parsing and print formatting.

Public API:
    parse_gguf(path) -> dict        GGUF metadata (no tensors read)
    vram_total() -> int              VRAM in bytes
    detect(path) -> dict             Model metadata from GGUF
    fit(detected, vram) -> dict      VRAM fit estimate
    load_registry() -> dict          Per-model overrides
    save_registry(reg) -> None
    scan() -> list[dict]             All models in ~/models
    find(fragment) -> dict           Match one model by name/alias
    plan_apply(fragment) -> dict     Dry-run: what WOULD a swap change?
"""

from __future__ import annotations

import json
import re
import struct
import time
from pathlib import Path
from typing import Any

from forge_env import plan_env, read_env, write_env

HOME = Path.home()
MODELS_DIR = HOME / "models"
ENVFILE = HOME / ".config/forge-stack/stack.env"
REGISTRY = HOME / ".config/forge-stack/models.json"

GIB = 1024**3

# Scan cache: avoids re-scanning GGUF files within a single request.
# A swap calls scan() up to 3 times (file resolution, plan_apply,
# reclaim lookup). With 5 models on NVMe this is ~tens of ms per
# call, but the cache eliminates the redundancy entirely.
_SCAN_CACHE: dict[str, Any] = {}
_SCAN_CACHE_TTL = 2.0  # seconds — long enough for one swap, short enough to notice new models

# arch (gguf general.architecture, prefix match) → DevForge prompt template
TEMPLATE_BY_ARCH: list[tuple[str, str]] = [
    ("qwen", "chatml"),
    ("yi", "chatml"),
    ("internlm", "chatml"),
    ("gemma", "gemma"),
]
# arch prefix → extra llama-server args
EXTRA_ARGS_BY_ARCH: list[tuple[str, str]] = [
    # --swa-full: without it every DevForge turn pays full prefill on
    # Gemma's interleaved sliding-window attention (measured June 2026)
    ("gemma", "--swa-full"),
]
CTX_CANDIDATES = [32768, 16384, 8192, 4096]
KV_BYTES_PER_EL = 1.07  # q8_0 KV cache
OVERHEAD = 0.8 * GIB  # compute graph + buffers (estimate)
RESERVE = 0.4 * GIB  # desktop/display headroom

# Conservative safety margin added in Phase 2 — the old estimator
# reported "tight, fits 15.0/16.0G" for Gemma 26B @ ctx 32768 but
# cudaMalloc failed at runtime. This margin kicks in before we write
# any config.
FIT_SAFETY_MARGIN = 0.6 * GIB  # measured: real allocation ~0.5G over estimate


# ── GGUF header parsing (metadata only, never reads tensors) ─────

_SCALARS: dict[int, tuple[str, int]] = {
    0: ("<B", 1),
    1: ("<b", 1),
    2: ("<H", 2),
    3: ("<h", 2),
    4: ("<I", 4),
    5: ("<i", 4),
    6: ("<f", 4),
    7: ("<B", 1),
    10: ("<Q", 8),
    11: ("<q", 8),
    12: ("<d", 8),
}


def parse_gguf(path: Path) -> dict[str, Any]:
    """Return all scalar + short-string metadata key/values."""
    meta: dict[str, Any] = {}
    with open(path, "rb") as f:
        if f.read(4) != b"GGUF":
            return meta
        struct.unpack("<I", f.read(4))  # version
        _, n_kv = struct.unpack("<QQ", f.read(16))

        def rstr(want: bool) -> str | None:
            n = struct.unpack("<Q", f.read(8))[0]
            if want and n <= 512:
                return f.read(n).decode("utf-8", "replace")
            f.seek(n, 1)
            return None

        def skip_value(t: int) -> None:
            if t in _SCALARS:
                f.seek(_SCALARS[t][1], 1)
            elif t == 8:
                rstr(False)
            elif t == 9:
                et = struct.unpack("<I", f.read(4))[0]
                cnt = struct.unpack("<Q", f.read(8))[0]
                if et in _SCALARS:
                    f.seek(_SCALARS[et][1] * cnt, 1)
                else:
                    for _ in range(cnt):
                        skip_value(et)

        for _ in range(n_kv):
            key = rstr(True) or ""
            t = struct.unpack("<I", f.read(4))[0]
            if t in _SCALARS:
                fmt, size = _SCALARS[t]
                meta[key] = struct.unpack(fmt, f.read(size))[0]
            elif t == 8:
                v = rstr(True)
                if v is not None:
                    meta[key] = v
            else:
                skip_value(t)
    return meta


def vram_total() -> int:
    for p in Path("/sys/class/drm").glob("card*/device/mem_info_vram_total"):
        try:
            v = int(p.read_text().strip())
            if v > 4 * GIB:
                return v
        except OSError:
            continue
    return 16 * GIB


def _slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")[:48]


def detect(path: Path) -> dict[str, Any]:
    m = parse_gguf(path)
    arch = str(m.get("general.architecture", ""))
    g = lambda k, d=None: m.get(f"{arch}.{k}", d)
    heads = g("attention.head_count") or 32
    if isinstance(heads, list):
        heads = heads[0]
    head_dim = g("attention.key_length") or ((g("embedding_length") or 4096) // max(int(heads), 1))
    kv_heads = g("attention.head_count_kv")
    if not isinstance(kv_heads, int):
        kv_heads = 8  # unknown/per-layer — conservative guess
    kv_per_tok = (g("block_count") or 40) * 2 * kv_heads * int(head_dim) * KV_BYTES_PER_EL
    if arch.startswith("gemma"):
        kv_per_tok *= 0.45  # interleaved SWA: most layers cache a small window
    # Prefer the structured name fields (basename + size_label) over
    # general.name, which often carries marketing suffixes. Parts are
    # deduplicated — many GGUFs repeat the size inside the basename.
    basename = str(m.get("general.basename") or m.get("general.name") or path.stem)
    size_label = str(m.get("general.size_label") or "")
    finetune = re.sub(r"-?(it|instruct|chat)$", "", str(m.get("general.finetune") or ""), flags=re.I)
    quant = ""
    qm = re.search(r"(i?q\d[_a-z0-9]*?)(?:\.gguf)?$", path.name.lower())
    if qm:
        quant = qm.group(1).rstrip("_-.")
    name = _slug(basename)
    if re.search(r"\d+b\b", name):
        size_label = ""  # basename already names the size (e.g. 26B-A4B)
    for part in (size_label, finetune, quant):
        p = _slug(part)
        if p and p not in name:
            name += f"-{p}"
    template = next((t for p, t in TEMPLATE_BY_ARCH if arch.startswith(p)), None)
    extra = " ".join(a for p, a in EXTRA_ARGS_BY_ARCH if arch.startswith(p))
    sampling = {k.split(".")[-1]: round(float(v), 2) for k, v in m.items() if k.startswith("general.sampling.")}
    return {
        "alias": name,
        "arch": arch or "unknown",
        "template": template or "chatml",
        "template_known": template is not None,
        "ctx_train": int(g("context_length") or 32768),
        "kv_per_tok": int(kv_per_tok),
        "moe": bool(g("expert_count")),
        "extra_args": extra,
        "size_bytes": path.stat().st_size,
        "sampling_hint": sampling,
    }


# KV-cache quantization scales the per-token cache size. kv_per_tok is
# computed at the q8_0 baseline (KV_BYTES_PER_EL); these multipliers adjust
# for the configured --cache-type-k. Without this, a q4_0 cache (half the
# memory) is over-counted 2x, so the estimator wrongly calls a fitting
# context "spills" and the hub swap pre-flight falsely refuses it.
_KV_CACHE_SCALE = {
    "f16": 2.0,
    "f32": 4.0,
    "bf16": 2.0,
    "q8_0": 1.0,
    "q5_1": 0.69,
    "q5_0": 0.66,
    "q4_1": 0.56,
    "q4_0": 0.53,
}


def kv_scale_from_args(base_args: str) -> float:
    """Read --cache-type-k from llama args and return its KV size multiplier
    relative to the q8_0 baseline (1.0). Defaults to 1.0 if unspecified."""
    m = re.search(r"--cache-type-k\s+(\S+)", base_args or "")
    return _KV_CACHE_SCALE.get(m.group(1), 1.0) if m else 1.0


def fit(d: dict[str, Any], vram: int, kv_scale: float = 1.0) -> dict[str, Any]:
    """Estimate VRAM fit for a model. Returns {status, ctx, need_gb}.

    Uses the FIT_SAFETY_MARGIN to avoid the optimistic estimate that
    caused F1 (26B @ ctx 32768 reported "tight, 15.0/16.0G" but OOMed).
    kv_scale adjusts the KV-cache cost for quantized caches (q4_0 ≈ 0.53).
    """
    budget = vram - RESERVE - FIT_SAFETY_MARGIN
    base = d["size_bytes"] + OVERHEAD
    kv_per_tok = d["kv_per_tok"] * kv_scale
    for ctx in CTX_CANDIDATES:
        if ctx > d["ctx_train"]:
            continue
        need = base + kv_per_tok * ctx
        if need <= budget:
            status = "tight" if need > budget - 0.7 * GIB else "fits"
            return {"status": status, "ctx": ctx, "need_gb": round(need / GIB, 1)}
    # nothing fits fully — it will spill into system RAM (runs, but slower)
    ctx = min(d["ctx_train"], 32768)
    need = base + kv_per_tok * ctx
    return {"status": "spills", "ctx": ctx, "need_gb": round(need / GIB, 1)}


# ── registry (auto-detected + user overrides) ────────────────────


def load_registry() -> dict[str, Any]:
    if REGISTRY.exists():
        try:
            return json.loads(REGISTRY.read_text())
        except Exception:
            pass
    return {}


def save_registry(reg: dict[str, Any]) -> None:
    REGISTRY.write_text(json.dumps(reg, indent=2))


def scan() -> list[dict[str, Any]]:
    # Return cached results if fresh (eliminates redundant scans within
    # a single swap request — plan_apply + reclaim lookup both call scan).
    now = time.time()
    if _SCAN_CACHE.get("ts", 0) > now - _SCAN_CACHE_TTL:
        return _SCAN_CACHE["results"]

    reg = load_registry()
    vram = vram_total()
    env = read_env(ENVFILE)
    # KV-cache quant set in LLAMA_BASE_ARGS scales the fit estimate (q4_0 ≈ ½).
    kv_scale = kv_scale_from_args(env.get("LLAMA_BASE_ARGS", ""))
    current = Path(env.get("MODEL", "")).name
    out, seen_aliases, changed = [], set(), False
    files = sorted(p for p in MODELS_DIR.glob("**/*.gguf") if not re.search(r"-0000[2-9]-of-", p.name))
    for p in files:
        key = p.name
        entry = reg.get(key, {})
        det: dict[str, Any] = detect(p)
        if entry.get("detected") != det:
            entry["detected"] = det
            entry.setdefault("overrides", {})
            reg[key] = entry
            changed = True
        eff: dict[str, Any] = {**det, **entry.get("overrides", {})}
        # unique alias
        alias: str = eff["alias"]
        while alias in seen_aliases:
            alias += "-2"
        seen_aliases.add(alias)
        eff["alias"] = alias
        f = fit(det, vram, kv_scale)
        if "ctx" in entry.get("overrides", {}):
            f = {**f, "ctx": int(entry["overrides"]["ctx"]), "status": f["status"] + " (ctx overridden)"}
        out.append(
            {
                "file": key,
                "path": str(p),
                "current": p.name == current,
                "fit": f,
                "vram_gb": round(vram / GIB, 1),
                "overrides": entry.get("overrides", {}),
                **eff,
            }
        )
    if changed:
        save_registry(reg)
    _SCAN_CACHE["ts"] = time.time()
    # Store a shallow copy so future callers can't mutate the cached list
    _SCAN_CACHE["results"] = list(out)
    return list(out)


class ModelError(Exception):
    """Raised when find() or plan_apply() can't resolve a fragment."""


def find(fragment: str) -> dict[str, Any]:
    """Match one model by filename or alias fragment. Raises ModelError on ambiguity."""
    models = scan()
    hits = [m for m in models if fragment.lower() in m["file"].lower() or fragment.lower() in m["alias"]]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise ModelError(f"no model matches '{fragment}' — see: forge-model list")
    raise ModelError(f"'{fragment}' is ambiguous: " + ", ".join(m["file"] for m in hits))


def plan_apply(fragment: str) -> dict[str, Any]:
    """Dry-run a model swap: return what WOULD change without writing.

    Returns a dict suitable for the UI/hub:
      { "model": {...}, "env_changes": {...}, "devforge_restart": "0"|"1",
        "llama_args": "...", "fit_warning": "..."|null, "vram_fatal": "..."|null }
    """
    m = find(fragment)
    env = read_env(ENVFILE)
    base = env.get("LLAMA_BASE_ARGS", "")
    if not base:
        return {"error": "stack.env is missing LLAMA_BASE_ARGS"}
    # Strip any stray surrounding quotes (defense-in-depth — read_env
    # already strips them, but config files can get hand-edited)
    base = base.strip().strip('"').strip("'")
    if "--n-predict" not in base:
        return {"error": "refusing: LLAMA_BASE_ARGS lost the --n-predict safety cap"}

    ctx = m["fit"]["ctx"]
    args = f"{base} --ctx-size {ctx}"
    if m["extra_args"]:
        args += f" {m['extra_args']}"

    old_template = env.get("DEVFORGE_PROMPT_TEMPLATE", "")
    old_ctx_match = re.search(r"--ctx-size\s+(\d+)", env.get("LLAMA_ARGS", ""))

    # Pass the RAW arg string (no quotes). write_env re-applies the original
    # quoting style of LLAMA_ARGS; pre-quoting here double-wraps the value into
    # `""...--swa-full""`, which llama rejects as an invalid argument.
    updates = {
        "MODEL": m["path"],
        "MODEL_ALIAS": m["alias"],
        "DEVFORGE_PROMPT_TEMPLATE": m["template"],
        "LLAMA_ARGS": args,
    }

    devforge_restart = (
        "1" if (m["template"] != old_template or not old_ctx_match or int(old_ctx_match.group(1)) != ctx) else "0"
    )

    env_plan = plan_env(ENVFILE, updates)

    fit_warning = None
    if m["fit"]["status"] == "spills":
        fit_warning = (
            f"exceeds VRAM — will spill to system RAM and run slower. Consider: forge-model set {m['alias']} ctx=8192"
        )

    return {
        "model": {
            "file": m["file"],
            "path": m["path"],
            "alias": m["alias"],
            "arch": m["arch"],
            "size_bytes": m["size_bytes"],
            "moe": m.get("moe", False),
            "template": m["template"],
            "template_known": m.get("template_known", True),
            "fit": m["fit"],
            "sampling_hint": m.get("sampling_hint"),
        },
        "env_changes": env_plan,
        "devforge_restart": devforge_restart,
        "llama_args": args,  # RAW (unquoted) — write_env re-quotes; see updates above
        "fit_warning": fit_warning,
        "vram_fatal": None,  # populated in Phase 2 with live VRAM check
    }


class ApplyError(Exception):
    """Raised when compute_apply can't complete (Phase 2 forward-compat —
    replaces sys.exit so the hub can catch it without crashing)."""


def compute_apply(fragment: str) -> dict[str, Any]:
    """Apply a model swap: write stack.env and return the result dict.

    Uses the plan from plan_apply to avoid recomputing args. Raises
    ApplyError on failure instead of sys.exit so the hub can catch it.
    """
    plan = plan_apply(fragment)
    if "error" in plan:
        raise ApplyError(plan["error"])

    updates = {
        "MODEL": plan["model"]["path"],
        "MODEL_ALIAS": plan["model"]["alias"],
        "DEVFORGE_PROMPT_TEMPLATE": plan["model"]["template"],
        "LLAMA_ARGS": plan["llama_args"],
    }

    write_env(ENVFILE, updates)
    return plan
