"""Authoritative Godot node type list — single source of truth.

REVIEW (Issue 2): The arch_planner.gbnf grammar and VALID_GODOT_TYPES in
scene_graph.py were maintained independently and had already drifted. This
module is now the single source of truth:

  * ``GODOT_NODE_TYPES`` is the authoritative Python set.
  * ``VALID_GODOT_TYPES`` (re-exported) is consumed by scene_graph.py.
  * ``generate_grammar_enum()`` emits the GBNF rule body for the
    ``godot-type`` enum so the grammar and validator cannot drift.
  * ``generate_grammar_file()`` reads the template grammar, replaces the
    ``godot-type`` rule with the auto-generated list, and writes the
    complete grammar file — call this at startup to keep the grammar
    and type registry in lockstep.

Usage::

    from devforge.knowledge.scene.godot_node_types import generate_grammar_file
    grammar_path = generate_grammar_file(output_dir="/tmp")
"""

from __future__ import annotations

import os
import re
from typing import Iterable


# ── Authoritative list ───────────────────────────────────────────
# Every Godot node type the LLM is allowed to emit in an entity.
# Add new types here, then re-run the grammar generator. Do not edit
# ``arch_planner.gbnf`` or ``VALID_GODOT_TYPES`` by hand.
GODOT_NODE_TYPES: frozenset[str] = frozenset(
    {
        # Core
        "Node",
        "Node2D",
        "Node3D",
        # 3D physics bodies
        "CharacterBody2D",
        "CharacterBody3D",
        "RigidBody2D",
        "RigidBody3D",
        "StaticBody2D",
        "StaticBody3D",
        "Area2D",
        "Area3D",
        "CollisionShape2D",
        "CollisionShape3D",
        # 3D visuals / cameras / lights
        "Camera2D",
        "Camera3D",
        "DirectionalLight3D",
        "OmniLight3D",
        "SpotLight3D",
        "SpringArm3D",
        "MeshInstance3D",
        "Sprite2D",
        "Sprite3D",
        "WorldEnvironment",
        "GPUParticles3D",
        "GPUParticles2D",
        # 2D / UI
        "CanvasLayer",
        "Control",
        "Label",
        "Button",
        "TextureRect",
        "ProgressBar",
        "ColorRect",
        "Panel",
        "LineEdit",
        "TextEdit",
        "GridContainer",
        "VBoxContainer",
        "HBoxContainer",
        # Animation / timing
        "AnimationPlayer",
        "Timer",
        # Navigation
        "NavigationAgent3D",
        "NavigationRegion3D",
        "Path3D",
        "PathFollow3D",
        # Audio
        "AudioStreamPlayer",
        "AudioStreamPlayer2D",
        "AudioStreamPlayer3D",
        # Misc
        "RayCast3D",
        "RayCast2D",
        "SubViewport",
        "Marker3D",
    }
)


# ── Re-export under the historical name ─────────────────────────
# scene_graph.py and other consumers can import this from one place.
VALID_GODOT_TYPES: frozenset[str] = GODOT_NODE_TYPES


# ── Property → allowed node types ────────────────────────────────
# Used by the operation validator to drop set_property ops whose
# property doesn't apply to the target node's Godot type. Without
# this check, one invalid op in an atomic batch_execute rolls back
# the entire build (Bug 1, 2026-06-14).
#
# Keys are property names as they appear in set_property ops.
# Values are sets of node-type prefixes or exact names that the
# property is valid for.  Substring match: "*Light3D" matches
# DirectionalLight3D, OmniLight3D, SpotLight3D.
#
# Properties NOT in this dict pass through unvalidated (to avoid
# over-blocking on types we haven't catalogued).
PROPERTY_ALLOWLIST: dict[str, set[str]] = {
    # Mesh / material — only on renderable geometry
    "mesh": {"MeshInstance3D"},
    "material_override": {
        "MeshInstance3D",
        "GeometryInstance3D",
        "Sprite3D",
        "CSGBox3D",
        "CSGSphere3D",
        "CSGCylinder3D",
        "CSGPolygon3D",
        "CSGCombiner3D",
        "CSGMesh3D",
    },
    "material_overlay": {
        "MeshInstance3D",
        "GeometryInstance3D",
        "Sprite3D",
    },
    # Shape — only on collision shapes
    "shape": {"CollisionShape3D", "CollisionShape2D"},
    # Light-specific properties
    "light_energy": {
        "DirectionalLight3D",
        "OmniLight3D",
        "SpotLight3D",
    },
    "light_color": {
        "DirectionalLight3D",
        "OmniLight3D",
        "SpotLight3D",
    },
    "light_negative": {
        "DirectionalLight3D",
        "OmniLight3D",
        "SpotLight3D",
    },
    "light_specular": {
        "DirectionalLight3D",
        "OmniLight3D",
        "SpotLight3D",
    },
    "shadow_enabled": {
        "DirectionalLight3D",
        "OmniLight3D",
        "SpotLight3D",
    },
    # Text — only on labels
    "text": {"Label", "LineEdit", "TextEdit", "Button"},
}


# Canonical denylist of node types that have NO Vector3 transform. In this 3D
# pipeline a `set_property position` (and the other transform props below)
# emits a Vector3 — valid on any spatial node, but invalid on UI / Timer /
# audio nodes. This is the single source of truth: the architecture compiler
# imports it (was a local `_NON_3D_TYPES` literal). `position` is handled as a
# DENYLIST rather than an allowlist because the set of types WITH a transform
# is huge (all Node3D + all CanvasItem) while the transform-less set is small.
NODES_WITHOUT_VECTOR3_TRANSFORM: set[str] = {
    "Node",
    "Timer",
    "CanvasLayer",
    "Label",
    "Button",
    "LineEdit",
    "TextEdit",
    "ColorRect",
    "Panel",
    "Control",
    "HBoxContainer",
    "VBoxContainer",
    "GridContainer",
    "MarginContainer",
    "CenterContainer",
    "ScrollContainer",
    "AspectRatioContainer",
    "Popup",
    "PopupMenu",
    "PopupPanel",
    "Window",
    "RichTextLabel",
    "TextureRect",
    "TextureButton",
    "CheckBox",
    "CheckButton",
    "MenuButton",
    "OptionButton",
    "SpinBox",
    "ProgressBar",
    "HSlider",
    "VSlider",
    "HSplitContainer",
    "VSplitContainer",
    "TabContainer",
    "TabBar",
    "ItemList",
    "Tree",
    "ColorPicker",
    "FileDialog",
    "AcceptDialog",
    "ConfirmationDialog",
    "GraphNode",
    "GraphEdit",
    "SubViewportContainer",
    "AnimationPlayer",
    "AnimationTree",
    "AudioStreamPlayer",
    "AudioStreamPlayer2D",
}

# Vector3 transform properties this pipeline emits onto spatial nodes.
VECTOR3_TRANSFORM_PROPS: frozenset[str] = frozenset(
    {
        "position",
        "rotation",
        "rotation_degrees",
        "scale",
        "transform",
        "global_position",
        "global_rotation",
        "global_rotation_degrees",
        "global_transform",
        "quaternion",
        "basis",
    }
)


def _property_matches_type(prop: str, node_type: str) -> bool | None:
    """Check whether *prop* is valid for *node_type*.

    Returns:
        True  — property IS in the allowlist and type matches.
        False — property is invalid for this type (allowlist miss, or a
                Vector3 transform prop on a transform-less node).
        None  — property is unknown for this type (allow / pass through).
    """
    # Transform props: denylist (see NODES_WITHOUT_VECTOR3_TRANSFORM).
    if prop in VECTOR3_TRANSFORM_PROPS:
        if node_type in NODES_WITHOUT_VECTOR3_TRANSFORM:
            return False
        return None  # spatial or uncatalogued → allow

    allowed = PROPERTY_ALLOWLIST.get(prop)
    if allowed is None:
        return None  # unknown → allow
    # Exact match
    if node_type in allowed:
        return True
    # Prefix match (e.g. DirectionalLight3D matches "*Light3D")
    for prefix in allowed:
        if prefix.endswith("*") and node_type.startswith(prefix[:-1]):
            return True
    return False


# ── Path to the template grammar ───────────────────────────────
# Relative to this file: ../../reasoning/prompts/arch_planner.gbnf
_GRAMMAR_TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "..", "reasoning", "prompts", "arch_planner.gbnf")


# ── Grammar generator ───────────────────────────────────────────
def generate_grammar_enum(types: Iterable[str] | None = None) -> str:
    """Emit the body of the ``godot-type`` rule for arch_planner.gbnf.

    Example output (one alternative per line, indented)::

        godot-type ::= "\\"Node\\""
                     | "\\"Node2D\\""
                     | "\\"Node3D\\""
                     ...

    The caller is responsible for emitting the ``godot-type ::=`` head
    and for placing this body inside the grammar file.
    """
    types = sorted(types if types is not None else GODOT_NODE_TYPES)
    if not types:
        return 'godot-type ::= "\\"Node3D\\""'

    lines: list[str] = []
    for i, t in enumerate(types):
        prefix = "             | " if i > 0 else "godot-type ::= "
        lines.append(f'{prefix}"\\"{t}\\""')
    return "\n".join(lines)


def generate_grammar_file(
    types: Iterable[str] | None = None,
    output_dir: str | None = None,
) -> str:
    """Generate a complete ``.gbnf`` grammar file from the template.

    Reads the template grammar (``arch_planner.gbnf``), replaces the
    ``godot-type ::=`` rule with the auto-generated list from
    ``GODOT_NODE_TYPES``, and writes the result to *output_dir*.

    Returns the path to the generated file so callers can pass it to
    ``RuntimeConfig.llama_grammar_path``.

    If *output_dir* is None, writes to the same directory as the
    template file (next to ``arch_planner.gbnf``).
    """
    types = types if types is not None else GODOT_NODE_TYPES
    template_path = os.path.normpath(_GRAMMAR_TEMPLATE)

    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Grammar template not found at {template_path}")

    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    # Replace the godot-type ::= ... rule with the auto-generated body.
    # The template has a multi-line godot-type rule; replace everything
    # from ``godot-type ::=`` up to the next top-level rule or EOF.
    new_enum = generate_grammar_enum(types)
    # Match: godot-type ::= ... (multi-line, until next non-indented rule or #-- or EOF)
    pattern = r"^godot-type ::= .*?(?=\n(?:[a-z]|connection-type ::=|# -{10,}|\Z))"
    generated = re.sub(pattern, new_enum, template, flags=re.MULTILINE | re.DOTALL)

    # llama.cpp's PEG-based GBNF parser rejects multi-line alternations
    # (and silently generates UNCONSTRAINED on parse failure) — write
    # the file in the single-line form both parsers accept.
    from devforge.infrastructure.llm.llama_client import normalize_gbnf

    generated = normalize_gbnf(generated)

    out_dir = output_dir or os.path.dirname(template_path)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "arch_planner_generated.gbnf")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(generated)

    return out_path


__all__ = [
    "GODOT_NODE_TYPES",
    "VALID_GODOT_TYPES",
    "PROPERTY_ALLOWLIST",
    "NODES_WITHOUT_VECTOR3_TRANSFORM",
    "VECTOR3_TRANSFORM_PROPS",
    "_property_matches_type",
    "generate_grammar_enum",
    "generate_grammar_file",
]
