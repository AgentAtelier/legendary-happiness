"""Architecture Planner — LLM-powered architecture delta generation.

Phase 10: Added in-memory LRU plan cache (world-state-aware keys)
and grammar-constrained JSON output via arch_planner.gbnf.

Phase 4: Added DeterministicPlanner for pattern-based pre-routing —
common requests (add player, rename node, delete entity) skip the
LLM entirely and return guaranteed-correct deltas.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from devforge.infrastructure.logger import logger


class PlanningError(Exception):
    """LLM planning failed — retryable."""

    pass


# ------------------------------------------------------------------
# Deterministic planner — pattern-based pre-routing
# ------------------------------------------------------------------


class DeterministicPlanner:
    """Resolves common requests without calling the LLM.

    Loads patterns from patterns/*.json and matches prompts against
    trigger keywords.  Also handles rename/remove via regex.
    """

    PATTERNS_DIR = Path(__file__).resolve().parents[2] / "patterns"

    # Rename: "rename Player to Hero" or "rename node Player to Hero"
    # Anchored to prompt start (full-prompt rename commands).
    RENAME_RE = re.compile(r"^rename\s+(?:node\s+)?(.+?)\s+to\s+(.+)$", re.IGNORECASE)
    # Delete: "delete node Player" or "remove Enemy"
    # Anchored to prompt start (full-prompt delete commands).
    DELETE_RE = re.compile(r"^(?:delete|remove)\s+(?:node\s+)?(.+)$", re.IGNORECASE)
    # Mid-prompt rename: "Create X, then rename it to Y" or
    # "Create X, then rename X to Y" (Bug 2, 2026-06-14).
    #
    # IMPORTANT: this regex detects the INTENT but does NOT return a
    # deterministic delta here — it only falls through to the LLM.
    # The engine._run_arch_path post-LLM pass injects _rename into
    # the delta. Returning here would skip the LLM entirely, so the
    # entity would never be created.
    MID_RENAME_RE = re.compile(
        r"(?:then|and)\s+rename\s+(?:the\s+(?:node|entity)\s+)?(.+?)\s+to\s+(.+?)(?:$|[.,;])",
        re.IGNORECASE,
    )

    def __init__(self):
        self._patterns: List[Dict[str, Any]] = []
        self._load_patterns()

    def _load_patterns(self) -> None:
        if not self.PATTERNS_DIR.exists():
            return
        for pat_file in sorted(self.PATTERNS_DIR.glob("*.json")):
            try:
                data = json.loads(pat_file.read_text())
                if "triggers" in data and "delta" in data:
                    self._patterns.append(data)
                    logger.info(
                        "det_planner",
                        f"Loaded pattern: {data.get('name', pat_file.stem)}",
                    )
            except Exception as exc:
                logger.warn("det_planner", f"Failed to load {pat_file}: {exc}")

    def match(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Try to satisfy the prompt deterministically.

        Returns an architecture delta dict on match, None otherwise.
        """
        norm = prompt.strip().lower()

        # ── Full-prompt rename ("rename X to Y") ──
        m = self.RENAME_RE.match(prompt.strip())
        if m:
            old_name = m.group(1).strip()
            new_name = m.group(2).strip()
            return {
                "systems": [],
                "entities": [],
                "connections": [],
                "_rename": {"from": old_name, "to": new_name},
            }

        # ── Full-prompt delete ("delete X") ──
        m = self.DELETE_RE.match(prompt.strip())
        if m:
            target = m.group(1).strip()
            return {
                "systems": [],
                "entities": [],
                "connections": [],
                "_remove": target,
            }

        # ── Mid-prompt rename ("create X, then rename X to Y") ──
        # Bug 2 (2026-06-14): detected but NOT returned here — the LLM must
        # still create the entity. engine._run_arch_path injects _rename
        # into the LLM's delta afterward. Returning a deterministic delta
        # here would skip entity creation entirely.
        # (engine._run_arch_path handles both rename and delete via its
        # _DELETE_INTENT_RE and _RENAME_TO_RE patterns.)

        # ── Pattern match ──
        # FIX (Issue 7): Substring matching previously hijacked any prompt
        # containing "player" / "enemy" / etc. (e.g. "Update Player.gd: add a
        # warmth variable") and bypassed the LLM. We now only fire on short,
        # imperative phrases like "add a player" / "create a merchant" — full
        # regex anchored to start/end with optional article.
        _SHORT_PROMPT_VERBS = r"(add|create|make|spawn|place|drop|put)"
        for pat in self._patterns:
            for trigger in pat.get("triggers", []):
                # Multi-word triggers (e.g. "playable character") are handled
                # by re.escape() on the trigger portion.
                pattern = r"^" + _SHORT_PROMPT_VERBS + r"\s+(a\s+|an\s+)?" + re.escape(trigger) + r"\s*$"
                if re.match(pattern, norm):
                    logger.info(
                        "det_planner",
                        f"Deterministic HIT: {pat['name']}",
                    )
                    return dict(pat["delta"])

        return None


# ------------------------------------------------------------------
# Architecture planner
# ------------------------------------------------------------------


class ArchitecturePlanner:
    """Generates architecture deltas from natural language prompts.

    Caches plans in an in-memory LRU cache keyed by prompt + scene +
    system graph state.  When a GBNF grammar is available, the LLM
    call is grammar-constrained to produce valid JSON on the first try.
    """

    def __init__(self, cache: Optional[Any] = None, grammar_path: Optional[str] = None):
        """Args:
        cache: Optional LRUPlanCache instance.
        grammar_path: Path to GBNF grammar for JSON output constraint.
        """
        self._cache = cache
        self._grammar_path = grammar_path
        self._grammar_text: Optional[str] = None
        self._deterministic = DeterministicPlanner()

        # Lazy-load grammar
        if grammar_path:
            self._load_grammar(grammar_path)
        # Workstream A2: capture raw LLM output for diagnostics
        self.last_raw_output: str = ""

    def plan(
        self,
        *,
        context: str,
        prompt: str,
        llm_fn: Callable[[str], str],
        scene: Optional[Dict] = None,
        graph: Optional[Any] = None,
        skip_cache: bool = False,
    ) -> Dict:
        """Generate an architecture delta, using cache if available.

        Args:
            context: Assembled context string for the LLM prompt.
            prompt: User's natural language spec.
            llm_fn: Callable that takes a prompt string and returns LLM output.
            scene: Current scene tree (for cache key).
            graph: Current SystemGraph (for cache key).
            skip_cache: If True, bypass the plan cache entirely (used by
                diagnostics/harness for repeat-diversity measurement).

        Returns:
            Architecture delta dict with systems, entities, and connections.
        """
        # ── Deterministic pre-routing ──
        det = self._deterministic.match(prompt)
        if det is not None:
            self.last_raw_output = ""  # A2: no LLM call, clear raw output
            # Idempotency: don't recreate entities that already exist
            if graph is not None:
                existing = set()
                for node in graph.nodes:
                    name = getattr(node, "name", None) or getattr(node, "id", None)
                    if name:
                        existing.add(name)
                det["entities"] = [e for e in det.get("entities", []) if e.get("name") not in existing]
            logger.info(
                "arch_planner",
                "Deterministic path — skipping LLM",
                prompt_preview=prompt[:100],
            )
            return det

        # ── Cache lookup ──
        if not skip_cache and self._cache is not None and scene is not None and graph is not None:
            cached = self._cache.get(prompt, scene, graph)
            if cached is not None:
                logger.info(
                    "arch_planner",
                    "Cache HIT",
                    systems=len(cached.get("systems", [])),
                )
                return cached

        # ── LLM call ──
        llm_prompt = self._build_prompt(context, prompt)

        logger.info(
            "arch_planner",
            "Calling LLM for architecture delta",
            prompt_preview=prompt[:100],
            grammar=self._grammar_path is not None,
            skip_cache=skip_cache,
        )

        try:
            response = llm_fn(llm_prompt)
            self.last_raw_output = response  # A2: capture for diagnostics
            result = self._parse_response(response)

            logger.info(
                "arch_planner",
                "Architecture delta parsed",
                systems=len(result.get("systems", [])),
                entities=len(result.get("entities", [])),
            )

            # ── Cache store ──
            if not skip_cache and self._cache is not None and scene is not None and graph is not None:
                self._cache.set(prompt, scene, graph, result)

            return result

        except Exception as exc:
            logger.error("arch_planner", f"LLM planning failed: {exc}")
            raise PlanningError(str(exc)) from exc

    def _load_grammar(self, path: str) -> None:
        """Load a GBNF grammar file for constraining LLM output."""
        try:
            grammar_file = Path(path)
            if grammar_file.exists():
                raw = grammar_file.read_text(encoding="utf-8")
                self._grammar_text = raw.replace("\r\n", "\n").strip()
                logger.info("arch_planner", f"Loaded grammar from {path}")
            else:
                logger.warn("arch_planner", f"Grammar file not found: {path}")
        except Exception as exc:
            logger.error("arch_planner", f"Failed to load grammar: {exc}")

    @property
    def grammar(self) -> Optional[str]:
        """The loaded GBNF grammar text for JSON output constraint."""
        return self._grammar_text

    @property
    def cache_stats(self) -> Optional[Dict]:
        """Cache hit/miss statistics (None if no cache configured)."""
        if self._cache is not None:
            return self._cache.stats()
        return None

    def _build_prompt(self, context: str, prompt: str) -> str:
        """Build the planner prompt with static-prefix-first ordering.

        For small models (4B-active Gemma), recency bias is strong —
        instructions closest to generation carry the most weight.
        One tight example trumps three; the final checklist catches
        the two errors this model makes most (recreating entities,
        invalid names).
        """
        return f"""
You are the architecture planner for a Godot 4 AI game development system.
Convert the user request into an architecture delta. Output JSON only.

Schema:

{{
  "systems": [{{"name": "SystemName", "description": "What it does"}}],
  "entities": [{{
    "name": "EntityName", "type": "CharacterBody3D",
    "parent": "ParentName",
    "props": {{"mesh": "capsule", "position": [0,1,0]}}
  }}],
  "connections": [{{"from": "EntityA", "to": "EntityB", "type": "signal"}}]
}}

"parent" is OPTIONAL: set it to the name of ANOTHER entity in this list to nest
a node under it. Omit "parent" only for top-level nodes (placed under the scene
root). HONOR the structure the request describes — when it says "under X" or "a
child of X", set that node's parent to X. Containers (Node3D groups, CanvasLayer
UI) must actually contain their children via "parent".

"props" is OPTIONAL: use to set per-node properties and resources. Allowed keys:
  "mesh": "box"|"sphere"|"capsule"|"plane"|"cylinder"   (MeshInstance3D only)
  "shape": "box"|"sphere"|"capsule"|"cylinder"          (CollisionShape3D only)
  "color": [r,g,b]   (RGB 0-1, sets material override color on MeshInstance3D)
  "position": [x,y,z]  (Vector3 world position)
  "text": "string"     (Label text content)
Props are applied to the entity itself: use mesh/color on MeshInstance3D,
shape on CollisionShape3D, text on Label, position on any Node3D.

IMPORTANT — props do NOT create child nodes. To give a node a collider or a
visible 3D shape you MUST add those as SEPARATE child entities:
  - a node that detects/blocks (Area3D, StaticBody3D, RigidBody3D) needs a
    CollisionShape3D CHILD entity (its parent = that node, props with "shape").
  - a node that should be VISIBLE as a 3D shape needs a MeshInstance3D CHILD
    entity (its parent = that node, props with "mesh" and optional "color").
Never collapse a collider or mesh into a prop on the parent — list the child
entity explicitly with its own "parent".

Allowed godot-type values: CharacterBody3D, Node3D, Area3D, Camera3D, StaticBody3D, MeshInstance3D, CollisionShape3D, CSGBox3D, CSGSphere3D, Path3D, NavigationAgent3D, Timer, AnimationPlayer, Sprite3D, Label3D, RayCast3D, AudioStreamPlayer3D, GPUParticles3D, OmniLight3D, SpotLight3D, DirectionalLight3D, WorldEnvironment, Node, Node2D, Control, ColorRect, Panel, Button, Label, LineEdit, TextEdit, GridContainer, VBoxContainer, HBoxContainer.

Allowed connection-type values: signal, depends_on, controls, uses.

Example:

Request: "A collectible coin (Area3D) with a sphere collider and a visible gold
sphere, plus a UI score label"
Output:

{{
  "systems": [
    {{"name": "CoinCollection", "description": "Body-entered signal handler: queue_free the coin and increment the ScoreLabel text"}},
    {{"name": "ScoreLabelUpdater", "description": "Updates the ScoreLabel with the current score"}}
  ],
  "entities": [
    {{"name": "Coin", "type": "Area3D", "props": {{"position": [0,1,0]}}}},
    {{"name": "CoinShape", "type": "CollisionShape3D", "parent": "Coin", "props": {{"shape": "sphere"}}}},
    {{"name": "CoinMesh", "type": "MeshInstance3D", "parent": "Coin", "props": {{"mesh": "sphere", "color": [1,0.8,0]}}}},
    {{"name": "UI", "type": "CanvasLayer"}},
    {{"name": "ScoreLabel", "type": "Label", "parent": "UI", "props": {{"text": "Score: 0"}}}}
  ],
  "connections": [{{"from": "Coin", "to": "ScoreLabel", "type": "signal", "signal": "body_entered", "method": "_on_body_entered"}}]
}}

CRITICAL — when the request describes behaviors (movement, WASD input,
collection, score tracking, spawning, signals, timers, or any game logic),
you MUST include at least one system describing that behavior. Systems
become GDScript files. If the request only creates static geometry with
no behavior, systems may be empty.

Existing architecture (do not recreate anything listed here):

{context}

Request: {prompt}

Before output, verify: (1) every name uses only letters, digits, underscores — no spaces or punctuation. (2) no entity name already appears in the Existing architecture above. (3) every type is from the Allowed list. (4) every node the request nests "under" another has a matching "parent". (5) mesh only on MeshInstance3D; shape only on CollisionShape3D; text only on Label; position on any Node3D subtype. (6) JSON only, no prose outside the braces. (7) systems are NOT empty when the request describes any behavior — include at least one system per distinct behavior.
Output JSON now:
"""

    def _parse_response(self, text: str, retry_context: str = "") -> Dict:
        if not text or not text.strip():
            raise ValueError("Empty LLM response")

        # Remove thinking tags
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)

        # Remove markdown fences
        text = re.sub(r"^```(?:json)?\s*", "", text.strip())
        text = re.sub(r"\s*```\s*$", "", text)

        start = text.find("{")

        if start == -1:
            raise ValueError(f"No JSON found in response:\n{text[:200]}")

        decoder = json.JSONDecoder()

        try:
            data, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in LLM response: {e}\n{text[:200]}")

        return {
            "systems": data.get("systems", []),
            "entities": data.get("entities", []),
            "connections": data.get("connections", []),
            # Forward optional per-entity ``parent`` so the compiler can
            # honor the model's parenting intent (e.g. Camera3D as a child
            # of SpringArm3D). Absent or empty parent → compiler falls back
            # to scene root.
            "parents": {
                e.get("name"): e.get("parent")
                for e in data.get("entities", [])
                if isinstance(e, dict) and e.get("name") and e.get("parent")
            },
        }
