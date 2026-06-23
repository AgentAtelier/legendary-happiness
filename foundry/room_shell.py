"""foundry.room_shell — orchestrate the Blender room-shell GLB with caching.

ensure_room_shell() returns a cached GLB for (w, d, wall_height, theme, seed),
building it via Blender on a cache miss. Returns None if Blender is unavailable
or generation fails (caller falls back to the inline box shell). The cache key
is authoritative (GPU bakes are not bit-exact)."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

GEN_VERSION = "1"
_DEFAULT_CACHE = Path.home() / ".cache" / "forge" / "room_shell"
_GEN = Path(__file__).resolve().parent / "blender" / "build_room_shell.py"
_TIMEOUT = 180


def _cache_dir(w, d, wall_height, theme, seed, cache_root=None) -> Path:
    root = Path(cache_root) if cache_root else _DEFAULT_CACHE
    key = f"{round(float(w),2)}|{round(float(d),2)}|{round(float(wall_height),2)}|{theme}|{int(seed)}|{GEN_VERSION}"
    h = hashlib.sha256(key.encode()).hexdigest()[:16]
    return root / h


def _run_blender(out_glb, w, d, wall_height, theme, seed) -> bool:
    blender = shutil.which("blender")
    if not blender:
        return False
    try:
        r = subprocess.run(
            [blender, "--background", "--python", str(_GEN), "--",
             str(out_glb), str(w), str(d), str(wall_height), str(theme), str(seed)],
            capture_output=True, timeout=_TIMEOUT)
        return r.returncode == 0 and Path(out_glb).exists()
    except (subprocess.TimeoutExpired, OSError):
        return False


def ensure_room_shell(w, d, wall_height, theme, seed=0, cache_root=None):
    if shutil.which("blender") is None:
        return None
    d_dir = _cache_dir(w, d, wall_height, theme, seed, cache_root)
    glb = d_dir / "shell.glb"
    if glb.exists():
        return glb
    d_dir.mkdir(parents=True, exist_ok=True)
    if _run_blender(glb, w, d, wall_height, theme, seed):
        return glb
    return None
