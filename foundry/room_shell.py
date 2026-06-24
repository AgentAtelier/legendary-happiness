"""foundry.room_shell — orchestrate the Blender room-shell GLB with caching.

ensure_room_shell() returns a cached GLB for (w, d, wall_height, theme, seed),
building it via Blender on a cache miss. Returns None if Blender is unavailable
or generation fails (caller falls back to the inline box shell). The cache key
is authoritative (GPU bakes are not bit-exact)."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from decisions import make_decision

GEN_VERSION = "3"  # 2: window openings; 3: palette/mtime in cache key + loud failures
_DEFAULT_CACHE = Path.home() / ".cache" / "forge" / "room_shell"
_GEN = Path(__file__).resolve().parent / "blender" / "build_room_shell.py"
_TIMEOUT = 180


def _windows_json(windows) -> str:
    """Canonical JSON for the windows list (sorted keys → deterministic key + arg)."""
    return json.dumps(list(windows or []), sort_keys=True, separators=(",", ":"))


def _cache_dir(w, d, wall_height, theme, seed, cache_root=None, windows=(), palette_hash: str = "") -> Path:
    root = Path(cache_root) if cache_root else _DEFAULT_CACHE
    key = (f"{round(float(w),2)}|{round(float(d),2)}|{round(float(wall_height),2)}"
           f"|{theme}|{int(seed)}|{_windows_json(windows)}|{palette_hash}|{GEN_VERSION}")
    h = hashlib.sha256(key.encode()).hexdigest()[:16]
    return root / h


def _run_blender(out_glb, w, d, wall_height, theme, seed, windows=()) -> bool:
    blender = shutil.which("blender")
    if not blender:
        return False
    try:
        r = subprocess.run(
            [blender, "--background", "--python", str(_GEN), "--",
             str(out_glb), str(w), str(d), str(wall_height), str(theme), str(seed),
             _windows_json(windows)],
            capture_output=True, timeout=_TIMEOUT)
        return r.returncode == 0 and Path(out_glb).exists()
    except (subprocess.TimeoutExpired, OSError):
        return False


def ensure_room_shell(w, d, wall_height, theme, seed=0, cache_root=None, windows=()):
    """Return ``(glb_path_or_None, decisions)``.

    Phase 0.3: Blender unavailability or build failure emits a Decision Point
    (severity=error) instead of silently returning None.
    """
    path: Path | None = None
    decisions: list = []

    if shutil.which("blender") is None:
        decisions.append(
            make_decision(
                code="shell.blender_unavailable",
                stage="shell",
                severity="error",
                context={},
                choices=(),
            )
        )
        return path, decisions

    d_dir = _cache_dir(w, d, wall_height, theme, seed, cache_root, windows)
    glb = d_dir / "shell.glb"
    if glb.exists():
        return glb, decisions

    d_dir.mkdir(parents=True, exist_ok=True)
    if _run_blender(glb, w, d, wall_height, theme, seed, windows):
        return glb, decisions

    # Build failed — emit Decision Point
    decisions.append(
        make_decision(
            code="shell.build_failed",
            stage="shell",
            severity="error",
            context={"returncode": "Blender process returned non-zero or timed out"},
            choices=(),
        )
    )
    return path, decisions
