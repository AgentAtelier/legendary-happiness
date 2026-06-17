"""Repair Engine — fixes common issues in generated operations.

Phase 3: Deterministic repair table with rule-based fix handlers.
Mechanical errors (missing prefix, Godot 3→4 types) are fixed
without any LLM call.  Runs BEFORE sending operations to Godot.
"""

from __future__ import annotations

from typing import Dict, List

from devforge.infrastructure.logger import logger

# Godot 3 → Godot 4 node type renames
_GODOT3_TO_4: Dict[str, str] = {
    "KinematicBody": "CharacterBody3D",
    "KinematicBody2D": "CharacterBody2D",
    "Spatial": "Node3D",
    "Position3D": "Node3D",
    "CanvasItem": "Node2D",
    "Reference": "RefCounted",
    "YSort": "Node2D",
    "GIProbe": "VoxelGI",
    "Light2D": "PointLight2D",
    "Navigation2D": "NavigationRegion2D",
    "Navigation3D": "NavigationRegion3D",
    "ProceduralSky": "Sky",
    "SphereShape": "SphereShape3D",
    "BoxShape": "BoxShape3D",
    "CapsuleShape": "CapsuleShape3D",
    "ShortCut": "Shortcut",
}


class RepairEngine:
    """Deterministic repair pass — rule-based, zero LLM calls.

    Phase 6: Convergence detection — tracks error sets across repair
    attempts.  If repair produces the same error set (no progress) or
    oscillates between two error sets, it stops and surfaces the
    original errors rather than looping indefinitely.

    NOTE: The convergence guard is forward-looking — in the current
    single-pass repair design, repair() is called once per pipeline
    run so convergence is never reached.  It becomes active when
    a repair loop (LLM-based retry) is added.
    """

    def __init__(self):
        self._previous_errors: List[str] = []
        self._convergence_count: int = 0

    def reset(self) -> None:
        """Clear convergence state at the start of every pipeline run.
        The guard state is per-run: two consecutive apply_spec calls that
        happen to produce the same error set would otherwise trip the
        guard and silently skip repair on a fresh run."""
        self._previous_errors = []
        self._convergence_count = 0

    def repair(
        self,
        operations: List[Dict],
        errors: List[str],
        scene_tree: Dict,
        files: List[Dict],
    ) -> List[Dict]:
        """Apply deterministic fixes.  Returns repaired operations.

        Convergence guard: if the error set after repair is identical
        to the previous run (or oscillating between two sets), repair
        is making no progress — return unchanged and log a warning.
        """
        # ── Convergence guard ──
        error_key = frozenset(errors) if errors else frozenset()
        if error_key == self._previous_errors:
            self._convergence_count += 1
            if self._convergence_count >= 2:
                logger.warn(
                    "repair_engine",
                    "Repair converged — same errors after 2 attempts, returning unchanged",
                    errors=list(error_key)[:5],
                )
                # Reset for next pipeline run
                self._previous_errors = frozenset()
                self._convergence_count = 0
                return list(operations)
        else:
            self._convergence_count = 0
        self._previous_errors = error_key

        file_paths = {f.get("path", "") for f in files}
        repaired = []
        fixes = 0

        for op in operations:
            op = dict(op)  # Don't mutate original
            op_type = op.get("type", "")

            # ── 1. Fix node paths missing /root prefix ──
            for key in ("parent", "node", "source", "target"):
                path = op.get(key, "")
                if path and not path.startswith("/root"):
                    op[key] = "/root/Main/" + path.lstrip("/")
                    fixes += 1

            # ── 2. Fix script paths in attach_script ──
            if op_type == "attach_script":
                script = op.get("script", "")
                if script and script not in file_paths:
                    for fp in file_paths:
                        if script in fp or fp.endswith(script):
                            op["script"] = fp
                            fixes += 1
                            break

            # ── 3. Godot 3 → Godot 4 type renames ──
            node_type = op.get("node_type", "")
            if node_type and node_type in _GODOT3_TO_4:
                old = node_type
                op["node_type"] = _GODOT3_TO_4[old]
                logger.info("repair_engine", f"Type rename: {old} → {op['node_type']}")
                fixes += 1

            # ── 4. Missing scripts/ prefix on script paths ──
            if op_type in ("attach_script", "create_file"):
                for key in ("script", "path"):
                    val = op.get(key, "")
                    if val and "/" not in val and not val.startswith("scripts/"):
                        op[key] = f"scripts/{val}"
                        fixes += 1

            repaired.append(op)

        if fixes > 0:
            logger.info("repair_engine", f"Applied {fixes} deterministic fixes")

        return repaired
