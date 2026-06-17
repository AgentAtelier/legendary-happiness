"""Ops Planner — LLM-powered direct operation generation.

Phase 6: Alternative to the ArchitecturePlanner→ArchitectureCompiler path.
When DEVFORGE_PLANNER=ops, the LLM emits Godot operations directly
(add_node, set_property, create_file, attach_script, connect_signal)
as a GBNF-constrained JSON array, bypassing the intermediate
architecture delta representation.

Used behind a flag for A/B testing before becoming default.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from devforge.infrastructure.logger import logger


class OpsPlanningError(Exception):
    """Ops planning failed — retryable."""
    pass


class OpsPlanner:
    """Generates Godot operations directly from natural language prompts.

    Uses a dedicated GBNF grammar (ops_planner.gbnf) to constrain
    the LLM to emit a valid JSON array of operations.  The output
    passes through completeness, validation, and repair just like
    the arch path.
    """

    GRAMMAR_FILENAME = "ops_planner.gbnf"

    def __init__(self, grammar_dir: Optional[str] = None):
        """Args:
            grammar_dir: Path to the directory containing ops_planner.gbnf.
                Defaults to the prompts directory next to arch_planner.gbnf.
        """
        self._grammar_text: Optional[str] = None
        self._load_grammar(grammar_dir)

    def _load_grammar(self, grammar_dir: Optional[str] = None) -> None:
        """Load the ops GBNF grammar from the prompts directory."""
        try:
            from devforge.reasoning.prompts import arch_planner as _ref
            prompts_dir = Path(_ref.__file__).parent
        except Exception:
            prompts_dir = Path(grammar_dir) if grammar_dir else Path(
                __file__
            ).resolve().parents[2] / "reasoning" / "prompts"

        grammar_path = prompts_dir / self.GRAMMAR_FILENAME

        if grammar_path.exists():
            raw = grammar_path.read_text(encoding="utf-8")
            self._grammar_text = raw.replace("\r\n", "\n").strip()
            logger.info("ops_planner", f"Loaded grammar from {grammar_path}")
        else:
            logger.warn("ops_planner", f"Grammar not found: {grammar_path}")

    @property
    def grammar(self) -> Optional[str]:
        """The loaded GBNF grammar for operation output constraint."""
        return self._grammar_text

    def plan(
        self,
        *,
        context: str,
        prompt: str,
        llm_fn: Callable[[str], str],
        scene: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Generate operations directly from the prompt.

        Args:
            context: Assembled context string for the LLM prompt.
            prompt: User's natural language spec.
            llm_fn: Callable that takes a prompt string and returns LLM output.
            scene: Current scene tree (for the prompt).

        Returns:
            Dict with keys:
              - files: List of {"path": str, "content": str} for scripts
              - operations: List of operation dicts for the executor
        """
        llm_prompt = self._build_prompt(context, prompt)

        logger.info(
            "ops_planner",
            "Calling LLM for direct operations",
            prompt_preview=prompt[:100],
            grammar=True,
        )

        try:
            response = llm_fn(llm_prompt)
            result = self._parse_response(response)

            logger.info(
                "ops_planner",
                "Operations parsed",
                files=len(result.get("files", [])),
                operations=len(result.get("operations", [])),
            )

            return result

        except Exception as exc:
            logger.error("ops_planner", f"LLM ops planning failed: {exc}")
            raise OpsPlanningError(str(exc)) from exc

    def _build_prompt(self, context: str, prompt: str) -> str:
        """Build the ops planner prompt.

        Teaches the model the exact operation schema so it emits
        correct operation JSON.  Includes the current scene tree
        so the model knows what already exists (no duplication).
        """
        return f"""You are the operations planner for a Godot 4 AI game development system.
Emit a JSON array of scene operations to fulfil the user request.

You may emit these FIVE operation types (and ONLY these five):

1. add_node — create a new node in the scene:
   {{"type":"add_node","parent":"/root/Main","node_type":"MeshInstance3D","name":"Player"}}
   parent: the EXISTING node to parent under (must already exist in the scene tree).
   node_type: one of the allowed Godot types (see list below).
   name: the new node's name (letters, digits, underscores only).

2. set_property — set a property on an existing node:
   {{"type":"set_property","node":"/root/Main/Player","property":"position","value":{{"x":0,"y":1,"z":0}}}}
   node: the FULL path to the target node.
   property: Godot property name (position, mesh, shape, material_override, text, etc.).
   value: JSON value (string, number, boolean, null, object, or array).

3. create_file — create a GDScript file:
   {{"type":"create_file","path":"scripts/player.gd","content":"extends Node3D\\n..."}}
   path: the script path relative to the project root.
   content: the full GDScript source code (escape newlines as \\\\n, quotes as \\\\").

4. attach_script — attach a script to a node:
   {{"type":"attach_script","node":"/root/Main/Player","script":"scripts/player.gd"}}
   node: the FULL path to the target node.
   script: the script path (same as the create_file path).

5. connect_signal — connect a signal from one node to a method on another:
   {{"type":"connect_signal","source":"/root/Main/Coin","signal":"body_entered","target":"/root/Main/Coin","method":"_on_body_entered"}}

RULES:
- Always create the script FIRST (create_file), then attach it (attach_script).
- Always add child nodes AFTER their parents exist in the scene.
- Set meshes on MeshInstance3D nodes: {{"property":"mesh","value":{{"__class__":"BoxMesh","size":{{"x":1,"y":1,"z":1}}}}}}
- Set shapes on CollisionShape3D nodes: {{"property":"shape","value":{{"__class__":"BoxShape3D","size":{{"x":1,"y":1,"z":1}}}}}}
- Set colors via material_override: {{"property":"material_override","value":{{"__class__":"StandardMaterial3D","albedo_color":{{"r":1,"g":0,"b":0,"a":1}}}}}}
- Set position: {{"property":"position","value":{{"x":0,"y":1,"z":0}}}}
- Set text on Label nodes: {{"property":"text","value":"Score: 0"}}
- NEVER create a node that already exists in the scene tree below.
- Output ONLY the JSON array, no prose outside the brackets.

Allowed node_type values:
Node3D, CharacterBody3D, StaticBody3D, Area3D, Camera3D, MeshInstance3D,
CollisionShape3D, CSGBox3D, CSGSphere3D, Path3D, NavigationAgent3D, Timer,
AnimationPlayer, Sprite3D, Label3D, RayCast3D, AudioStreamPlayer3D,
GPUParticles3D, OmniLight3D, SpotLight3D, DirectionalLight3D,
WorldEnvironment, Node, Node2D, Control, ColorRect, Panel, Button, Label,
LineEdit, TextEdit, GridContainer, VBoxContainer, HBoxContainer,
SpringArm3D, CanvasLayer, ProgressBar

Current scene tree (do NOT recreate nodes that already exist):
{context}

Request: {prompt}

Output JSON array now:
"""

    def _parse_response(self, text: str) -> Dict[str, Any]:
        """Parse the LLM response into files and operations."""
        if not text or not text.strip():
            raise OpsPlanningError("Empty LLM response")

        # Remove thinking tags
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)

        # Remove markdown fences
        text = re.sub(r"^```(?:json)?\s*", "", text.strip())
        text = re.sub(r"\s*```\s*$", "", text)

        start = text.find("[")
        if start == -1:
            raise OpsPlanningError(
                f"No JSON array found in response:\n{text[:200]}"
            )

        decoder = json.JSONDecoder()
        try:
            data, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError as e:
            raise OpsPlanningError(
                f"Invalid JSON in LLM response: {e}\n{text[:200]}"
            )

        if not isinstance(data, list):
            raise OpsPlanningError(
                f"Expected JSON array, got {type(data).__name__}"
            )

        # Split into files and operations
        files: List[Dict[str, Any]] = []
        operations: List[Dict[str, Any]] = []

        for item in data:
            if not isinstance(item, dict):
                continue
            op_type = item.get("type", "")
            if op_type == "create_file":
                files.append({
                    "path": item.get("path", ""),
                    "content": item.get("content", ""),
                })
            else:
                operations.append(item)

        return {"files": files, "operations": operations}
