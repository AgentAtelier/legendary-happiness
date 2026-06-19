"""Scene compiler — deterministic spec→Godot .tscn generator.

Turns a quest spec + placed-entity manifest into a runnable Godot
scene (.tscn) for the rpg project, wiring everything by a fixed
tag→behaviour table.  The LLM never appears here.

Mirrors ``foundry/publish.py`` for path/resource handling.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Tuple, TypedDict


# ── Manifest entry shape ─────────────────────────────────────────

class PlacedEntity(TypedDict, total=False):
    id: str
    category: str       # "table" | "shelf" | "chair" | "cabinet"
    material: str        # "worn_oak" | "rough_granite" | ...
    wear: float          # 0.15 .. 1.0
    x: float             # world position
    y: float
    z: float


# ── Tag → component table ────────────────────────────────────────
# P5 wires these into the .tscn.  Kept here as the single source of
# truth for which tag maps to which component script path.

_TAG_TABLE: Dict[str, str | None] = {
    "pickup": "res://scripts/pickup.gd",
    "talk": "res://scripts/talk.gd",
    "give": "res://scripts/give.gd",
    "inert": None,
}

# ── Shell node definitions ───────────────────────────────────────
# Placeholder nodes the compiler always emits.  P4 replaces them
# with real templates.

_SHELL_NODES: List[dict] = [
    {"name": "Player", "type": "CharacterBody3D", "parent": "."},
    {"name": "Camera3D", "type": "Camera3D", "parent": "Player"},
    {"name": "HUD", "type": "Control", "parent": "."},
    {"name": "WinScreen", "type": "Control", "parent": "."},
]

# ── NPC body primitive marker ────────────────────────────────────
# P7 replaces this with a procedurally generated humanoid GLB.
# For now: a CapsuleMesh (generated primitive, not imported).

_NPC_PRIMITIVE = {
    "type": "CapsuleMesh",
    "height": 1.8,
    "radius": 0.3,
}


def _glb_res_path(category: str, material: str, assets_subdir: str = "assets") -> str:
    """Build the res:// path for a placed entity's GLB.

    Mirrors publish.py convention: ``res://{assets_subdir}/{category}_{material}.glb``.
    """
    return f"res://{assets_subdir}/{category}_{material}.glb"


def _resolve_unique_glbs(manifest: List[PlacedEntity]) -> List[Tuple[str, str]]:
    """Return sorted unique (category, material) pairs from the manifest."""
    seen: set[Tuple[str, str]] = set()
    result: list[Tuple[str, str]] = []
    for entry in manifest:
        pair = (entry.get("category", "?"), entry.get("material", "default"))
        if pair not in seen:
            seen.add(pair)
            result.append(pair)
    result.sort()
    return result


def _ext_resource_block(unique_glbs: List[Tuple[str, str]], assets_subdir: str) -> str:
    """Build the [ext_resource] header block for unique GLBs.

    Omits the ``uid`` attribute intentionally — Godot auto-generates
    UIDs on import, and omitting them keeps the output deterministic
    (same input → byte-identical .tscn).
    """
    lines: list[str] = []
    for idx, (category, material) in enumerate(unique_glbs, start=1):
        path = _glb_res_path(category, material, assets_subdir)
        lines.append(
            f'[ext_resource type="PackedScene" path="{path}" id="{idx}"]'
        )
    return "\n".join(lines)


def _fmt_pos(v: float) -> str:
    """Format a position value: 0.0 → 0, 1.0 → 1, 0.5 → 0.5."""
    if v == int(v):
        return str(int(v))
    return str(v)


def compile_scene(
    quest_spec: dict,
    manifest: List[PlacedEntity],
    output_path: str,
    assets_subdir: str = "assets",
    scene_uid: str | None = None,
) -> str:
    """Compile a quest spec + manifest into a Godot .tscn file.

    Also writes a ``_quest_data.json`` file alongside the .tscn
    containing dialogue, objective, and quest metadata so the
    scene loader (P5) can read it without parsing .tscn metadata.

    Args:
        quest_spec: Validated quest spec from ``QuestBehaviourPlanner.plan()``.
        manifest: List of placed entities with at least ``id``, ``category``,
                  ``material``, and optional ``x``, ``y``, ``z``.
        output_path: File path to write the .tscn to (e.g.
                     ``/home/.../rpg/scenes/slice1_fetch.tscn``).
        assets_subdir: Subdirectory where GLBs live (default ``"assets"``).
        scene_uid: Optional Godot UID for the scene.  Only emitted when
                   provided (keeps tests deterministic).

    Returns:
        The *output_path* (so callers can assert the file was written).
    """
    target_entity = quest_spec["target_entity"]
    npc_role = quest_spec.get("npc_role", "villager")
    objective = quest_spec.get("objective", {})
    dialogue = quest_spec.get("dialogue", {})

    unique_glbs = _resolve_unique_glbs(manifest)

    # ── Write quest data as a JSON file alongside the .tscn ──────
    output_dir = str(Path(output_path).parent)
    tscn_stem = Path(output_path).stem  # e.g. "slice1_fetch"
    data_filename = f"{tscn_stem}_quest_data.json"
    data_path = str(Path(output_dir) / data_filename)
    # Derive the res:// path from the directory name the .tscn lives in
    dir_name = Path(output_path).parent.name or "scenes"
    data_res_path = f"res://{dir_name}/{data_filename}"

    quest_data: dict = {
        "npc_role": npc_role,
        "target_entity": target_entity,
        "dialogue": dialogue,
        "objective": objective,
    }
    Path(data_path).write_text(
        json.dumps(quest_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # ── Build .tscn content ─────────────────────────────────────
    lines: list[str] = []

    # Header
    # load_steps = ext_resources (GLBs + quest_data JSON) + sub_resources (npc_mesh + npc_mat)
    total_load_steps = len(unique_glbs) + 1 + 2  # GLBs + JSON + 2 subs
    header = f'[gd_scene load_steps={total_load_steps} format=3]'
    if scene_uid:
        header = f'[gd_scene load_steps={total_load_steps} format=3 uid="{scene_uid}"]'
    lines.append(header)
    lines.append("")

    # ExtResources: GLBs
    ext_block = _ext_resource_block(unique_glbs, assets_subdir)
    if ext_block:
        lines.append(ext_block)
    # ExtResource: quest data JSON (id is after GLB ids)
    data_ext_id = str(len(unique_glbs) + 1)
    lines.append(
        f'[ext_resource type="Resource" path="{data_res_path}" id="{data_ext_id}"]'
    )
    lines.append("")

    # Sub-resources for NPC body
    lines.append(
        f'[sub_resource type="{_NPC_PRIMITIVE["type"]}" id="npc_mesh"]'
    )
    lines.append(f'height = {_NPC_PRIMITIVE["height"]}')
    lines.append(f'radius = {_NPC_PRIMITIVE["radius"]}')
    lines.append("")
    lines.append(
        '[sub_resource type="StandardMaterial3D" id="npc_mat"]'
    )
    lines.append('albedo_color = Color(0.4, 0.5, 0.7, 1)')
    lines.append("")

    # Root
    lines.append('[node name="Root" type="Node3D"]')
    lines.append("")

    # Placed props
    glb_ids: dict[Tuple[str, str], str] = {}
    for i, (cat, mat) in enumerate(unique_glbs, start=1):
        glb_ids[(cat, mat)] = str(i)

    for entry in manifest:
        eid = entry["id"]
        cat = entry.get("category", "?")
        mat = entry.get("material", "default")
        x = entry.get("x", 0.0)
        y = entry.get("y", 0.0)
        z = entry.get("z", 0.0)
        tag = "pickup" if eid == target_entity else "inert"
        glb_id = glb_ids.get((cat, mat), "1")

        lines.append(f'[node name="{eid}" type="Node3D" parent="Root"]')
        lines.append(
            f"transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, "
            f"{_fmt_pos(x)}, {_fmt_pos(y)}, {_fmt_pos(z)})"
        )
        lines.append(f'metadata/_forge_tag = "{tag}"')
        lines.append("")

        lines.append(
            f'[node name="{eid}_model" type="Node3D" parent="{eid}"]'
        )
        lines.append(f'instance = ExtResource("{glb_id}")')
        lines.append("")

    # NPC node
    npc_x, npc_y, npc_z = 0.0, 0.0, -2.0
    lines.append('[node name="NPC" type="Node3D" parent="Root"]')
    lines.append(
        f"transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, "
        f"{_fmt_pos(npc_x)}, {_fmt_pos(npc_y)}, {_fmt_pos(npc_z)})"
    )
    lines.append('metadata/_forge_tag = "talk"')
    lines.append('metadata/_forge_tag_give = "give"')
    lines.append("")
    lines.append('[node name="Body" type="MeshInstance3D" parent="NPC"]')
    lines.append('mesh = SubResource("npc_mesh")')
    lines.append('material_override = SubResource("npc_mat")')
    lines.append("")

    # Shell nodes (placeholders)
    for shell in _SHELL_NODES:
        lines.append(
            f'[node name="{shell["name"]}" type="{shell["type"]}" '
            f'parent="{shell["parent"]}"]'
        )
        if shell["name"] == "Camera3D":
            lines.append(
                "transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 1.7, 0)"
            )
            lines.append("current = true")
        if shell["name"] == "WinScreen":
            lines.append("visible = false")
        lines.append("")

    # QuestData node (references the JSON resource)
    lines.append('[node name="QuestData" type="Node" parent="Root"]')
    lines.append(f'script = ExtResource("{data_ext_id}")')
    lines.append("")

    content = "\n".join(lines)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(content, encoding="utf-8")
    return output_path


def _parse_scene_text(tscn_text: str) -> dict:
    """Parse a .tscn text into a structured dict for test assertions.

    Returns a dict with keys: ``ext_resources``, ``nodes``, and
    ``metadata`` (a dict keyed by node name → metadata key-value pairs).
    Handles ``instance = ExtResource(...)`` on property lines below
    ``[node]`` declarations.
    """
    ext_resources: list[dict] = []
    nodes: list[dict] = []
    metadata: dict[str, dict[str, str]] = {}
    current_node: dict | None = None

    for line in tscn_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("[ext_resource "):
            id_match = re.search(r'id="([^"]+)"', stripped)
            path_match = re.search(r'path="([^"]+)"', stripped)
            ext_resources.append({
                "id": id_match.group(1) if id_match else "",
                "path": path_match.group(1) if path_match else "",
            })

        elif stripped.startswith("[node "):
            if current_node:
                nodes.append(current_node)
            name_match = re.search(r'name="([^"]+)"', stripped)
            type_match = re.search(r'type="([^"]+)"', stripped)
            parent_match = re.search(r'parent="([^"]+)"', stripped)
            instance_match = re.search(
                r'instance\s*=\s*ExtResource\("([^"]+)"\)', stripped
            )
            current_node = {
                "name": name_match.group(1) if name_match else "",
                "type": type_match.group(1) if type_match else "",
                "parent": parent_match.group(1) if parent_match else "",
                "instance": instance_match.group(1) if instance_match else None,
            }
            metadata[current_node["name"]] = {}

        elif current_node and (
            stripped.startswith(("instance ", "transform ", "metadata/",
                                 "mesh ", "material_override ", "script ",
                                 "current ", "visible ", "height ", "radius ",
                                 "albedo_color "))
        ):
            # Property line for the current node
            if stripped.startswith("instance = ExtResource"):
                m = re.search(
                    r'instance\s*=\s*ExtResource\("([^"]+)"\)', stripped
                )
                if m:
                    current_node["instance"] = m.group(1)
            elif stripped.startswith("metadata/"):
                key_val = stripped[len("metadata/"):]
                eq = key_val.find(" = ")
                if eq != -1:
                    key = key_val[:eq].strip()
                    val = key_val[eq + 3:].strip().strip('"')
                    metadata[current_node["name"]][key] = val

    if current_node:
        nodes.append(current_node)

    return {
        "ext_resources": ext_resources,
        "nodes": nodes,
        "metadata": metadata,
    }


def read_quest_data(tscn_path: str) -> dict | None:
    """Read the quest_data.json file alongside a compiled .tscn.

    Returns the parsed dict or None if the JSON file is missing.
    """
    tscn = Path(tscn_path)
    data_file = tscn.with_name(f"{tscn.stem}_quest_data.json")
    if not data_file.exists():
        return None
    return json.loads(data_file.read_text(encoding="utf-8"))
