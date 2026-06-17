"""Completeness Checker — injects required nodes automatically.

Examples:
- CharacterBody3D gets CollisionShape3D
- Scene gets Camera3D if missing
- Scene gets DirectionalLight3D if missing
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from devforge.infrastructure.logger import logger
from devforge.knowledge.scene.resource_templates import MESH_RESOURCES


class CompletenessChecker:

    def enforce(
        self,
        files: List[Dict],
        operations: List[Dict],
        scene_tree: Dict[str, Any],
    ) -> List[Dict]:

        operations = list(operations)
        node_index = self._collect_nodes(scene_tree, operations)
        added = 0

        # ── CharacterBody3D needs CollisionShape3D ──
        # D6: Wrap each injection rule with per-error handling.
        # Previously one malformed injection (e.g. a bad path from a
        # corrupted scene) killed the whole completeness pass. Now each
        # rule is isolated — one failure logs+skips, the rest proceed.
        for path, node_type in list(node_index.items()):
            if node_type in ("CharacterBody3D", "CharacterBody2D"):
                try:
                    dim = "3D" if "3D" in node_type else "2D"
                    collision = f"{path}/CollisionShape{dim}"
                    if collision not in node_index:
                        operations.append({
                            "type": "add_node",
                            "parent": path,
                            "node_type": f"CollisionShape{dim}",
                            "name": f"CollisionShape{dim}",
                        })
                        node_index[collision] = f"CollisionShape{dim}"
                        added += 1
                except Exception as exc:
                    logger.warn(
                        "completeness",
                        f"CollisionShape injection failed for {path}: {exc} — skipping",
                    )

        # ── Camera3D if missing (3D scenes only) ──
        has_3d = any(t.endswith("3D") for t in node_index.values())
        if has_3d and not self._has_node_type(node_index, "Camera3D"):
            try:
                root_path = self._find_root(node_index, operations)
                operations.append({
                    "type": "add_node",
                    "parent": root_path,
                    "node_type": "Camera3D",
                    "name": "MainCamera",
                })
                added += 1
            except Exception as exc:
                logger.warn(
                    "completeness",
                    f"Camera3D injection failed: {exc} — skipping",
                )

        # ── DirectionalLight3D if missing (3D scenes only) ──
        if has_3d and not self._has_node_type(node_index, "DirectionalLight3D"):
            try:
                root_path = self._find_root(node_index, operations)
                operations.append({
                    "type": "add_node",
                    "parent": root_path,
                    "node_type": "DirectionalLight3D",
                    "name": "DirectionalLight",
                })
                added += 1
            except Exception as exc:
                logger.warn(
                    "completeness",
                    f"DirectionalLight3D injection failed: {exc} — skipping",
                )

        # ── MeshInstance3D needs a mesh or it renders nothing ──
        # A bare MeshInstance3D is invisible; the user-visible symptom is
        # "the AI created my cube but I can't see it". Give every newly
        # added MeshInstance3D without an accompanying mesh set_property
        # a default BoxMesh — visible immediately, trivially replaced.
        try:
            mesh_set_for = {
                op.get("node")
                for op in operations
                if op.get("type") == "set_property" and op.get("property") == "mesh"
            }
            for op in list(operations):
                if op.get("type") != "add_node":
                    continue
                if op.get("node_type") != "MeshInstance3D":
                    continue
                node_path = f"{op.get('parent')}/{op.get('name')}"
                if node_path in mesh_set_for:
                    continue
                operations.append({
                    "type": "set_property",
                    "node": node_path,
                    "property": "mesh",
                    "value": MESH_RESOURCES["box"],
                })
                added += 1
        except Exception as exc:
            logger.warn(
                "completeness",
                f"Mesh injection failed: {exc} — skipping",
            )

        if added > 0:
            logger.info("completeness", f"Injected {added} required nodes")

        return operations

    def _collect_nodes(self, scene_tree: Dict, operations: List[Dict]) -> Dict[str, str]:
        nodes = {}
        # Index using the SAME path convention as SceneGraph / the validator:
        # the edited root node lives at /root/<RootName> (e.g. /root/Main), NOT
        # bare /root. Scanning from "/root" dropped the root node's name, so
        # every node was indexed one level too shallow (/root/Camera3D instead
        # of /root/Main/Camera3D). That made _find_root miss /root/Main and fall
        # back to an arbitrary child (/root/Camera3D), so every auto-injected
        # node (Camera3D / DirectionalLight3D) got an invalid parent path the
        # validator rejected — which made apply_spec refuse to execute ANY ops
        # on a scene missing a light or camera (including the real main.tscn).
        root_name = (scene_tree or {}).get("name") or "Main"
        self._scan_scene(scene_tree, f"/root/{root_name}", nodes)

        for op in operations:
            if op.get("type") == "add_node":
                parent = op.get("parent")
                name = op.get("name")
                node_type = op.get("node_type")
                if parent and name:
                    nodes[f"{parent}/{name}"] = node_type

        return nodes

    def _scan_scene(self, node: Dict, path: str, index: Dict[str, str]) -> None:
        node_type = node.get("type")
        if node_type:
            index[path] = node_type
        for child in node.get("children", []):
            child_name = child.get("name", "Node")
            self._scan_scene(child, f"{path}/{child_name}", index)

    def _has_node_type(self, node_index: Dict[str, str], node_type: str) -> bool:
        return any(t == node_type for t in node_index.values())

    def _find_root(
        self,
        node_index: Dict[str, str],
        operations: Optional[List[Dict]] = None,
    ) -> str:
        """Find the best root path to add nodes to.

        FIX (Issue 4): Previously fell back to ``/root`` (Godot's global
        scope), which put injected nodes like Camera3D / DirectionalLight3D
        outside the active scene. New priority:
          1. ``/root/Main`` if present in the index.
          2. The parent of the first ``add_node`` operation in the pending
             list (this is what the user actually asked us to add to).
          3. The first non-/root path at depth 2 in the index.
          4. ``/root/Main`` as the safe scene-root default (never ``/root``).
        """
        # Resolve the ACTUAL scene root: the unique ``/root/<RootName>`` entry
        # (depth-2 path under /root). Hardcoding "/root/Main" injected the
        # camera/light scaffold at a non-existent path whenever the live root
        # wasn't literally "Main" (e.g. a prior build left it "Main2"); the
        # bridge then created a fresh "Main" → Godot auto-suffixed it → the
        # whole scene cascaded under a rogue root. Resolve it live instead.
        for path in node_index:
            if path.startswith("/root/") and path.count("/") == 2:
                return path

        # Prefer the parent of the first add_node op, if any
        if operations:
            for op in operations:
                if op.get("type") == "add_node":
                    parent = op.get("parent")
                    if parent and parent != "/root":
                        return parent
                    break  # only consult the first add_node

        # Safe scene-root default — never Godot's global ``/root``
        return "/root/Main"
