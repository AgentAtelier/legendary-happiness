"""Operation Validator — checks operations before sending to Godot.

Returns (valid_ops, errors) tuple. Invalid ops are filtered out
with error messages explaining why.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from devforge.infrastructure.logger import logger
from devforge.knowledge.scene.godot_node_types import _property_matches_type
from devforge.knowledge.scene.scene_graph import VALID_GODOT_TYPES, SceneGraph

SUPPORTED_OPERATIONS = {
    "add_node",
    "remove_node",
    "rename_node",
    "attach_script",
    "set_property",
    "connect_signal",
    "add_child_scene",
}


class OperationValidator:
    def validate(
        self,
        operations: List[Dict],
        scene_tree: Dict[str, Any],
        files: List[Dict],
    ) -> Tuple[List[Dict], List[str]]:
        """Validate operations. Returns (valid_ops, error_messages)."""

        scene = SceneGraph(scene_tree)
        file_paths = {f.get("path", "") for f in files if f.get("path")}

        # Also track paths + types that add_node operations will create
        pending_paths: set[str] = set()
        pending_types: dict[str, str] = {}  # path → node_type

        valid = []
        errors = []

        for i, op in enumerate(operations):
            op_type = op.get("type", "")

            if op_type not in SUPPORTED_OPERATIONS:
                errors.append(f"Op {i}: unknown type '{op_type}'")
                continue

            method = getattr(self, f"_validate_{op_type}", None)
            if method:
                ok, err = method(op, scene, file_paths, pending_paths, pending_types)
                if ok:
                    valid.append(op)
                    # Track nodes this op creates
                    if op_type == "add_node":
                        parent = op.get("parent", "")
                        name = op.get("name", "")
                        node_type = op.get("node_type", "")
                        if parent and name:
                            full_path = f"{parent}/{name}"
                            pending_paths.add(full_path)
                            if node_type:
                                pending_types[full_path] = node_type
                else:
                    errors.append(f"Op {i} ({op_type}): {err}")
            else:
                # Supported type with no _validate_<type> method: passes through
                # UNCHECKED. Warn loudly so a newly-added op type can't silently
                # reach execution without a validator (D4).
                logger.warn(
                    "validator",
                    f"Op {i} type '{op_type}' is in SUPPORTED_OPERATIONS but has "
                    f"no _validate_{op_type}() — passing through UNVALIDATED. "
                    f"Add a validator method.",
                )
                valid.append(op)

        logger.info("validator", f"Validated: {len(valid)} valid, {len(errors)} errors")

        return valid, errors

    def _validate_add_node(self, op, scene, files, pending, pending_types) -> Tuple[bool, str]:
        parent = op.get("parent")
        node_type = op.get("node_type")
        name = op.get("name")

        if not parent:
            return False, "missing parent path"
        if not node_type:
            return False, "missing node_type"
        if not name:
            return False, "missing name"

        # Check parent exists (in scene or in pending ops)
        if not scene.has_path(parent) and parent not in pending:
            return False, f"parent '{parent}' not found in scene"

        # Validate Godot type
        if node_type not in VALID_GODOT_TYPES:
            return False, f"invalid Godot type '{node_type}'"

        return True, ""

    def _validate_remove_node(self, op, scene, files, pending, pending_types) -> Tuple[bool, str]:
        node = op.get("node")
        if not node:
            return False, "missing node path"
        # Check both the live scene AND pending paths (nodes created in the
        # same batch — "create X then delete X" requires the remove to
        # reference a same-batch add_node).  Without the pending check,
        # remove_node on a same-batch create fails validation and the
        # entire atomic batch rolls back (node_delete: 0 nodes).
        if not scene.has_path(node) and node not in pending:
            return False, f"node '{node}' not found"
        return True, ""

    def _validate_rename_node(self, op, scene, files, pending, pending_types) -> Tuple[bool, str]:
        node = op.get("node")
        new_name = op.get("new_name")
        if not node or not new_name:
            return False, "missing node or new_name"
        # Same as _validate_remove_node: check both the live scene AND
        # pending paths for same-batch "create X then rename X" prompts.
        if not scene.has_path(node) and node not in pending:
            return False, f"node '{node}' not found"
        return True, ""

    def _validate_attach_script(self, op, scene, files, pending, pending_types) -> Tuple[bool, str]:
        node = op.get("node")
        script = op.get("script")

        if not node or not script:
            return False, "missing node or script"

        # Node must exist or be pending
        if not scene.has_path(node) and node not in pending:
            # Try to find it with /root/Main prefix
            alt = f"/root/Main/{node.split('/')[-1]}"
            if scene.has_path(alt) or alt in pending:
                op["node"] = alt  # Fix the path
            else:
                return False, f"node '{node}' not found in scene"

        # Script should be in the generated files
        if script not in files:
            logger.warn("validator", f"Script '{script}' not in generated files, may already exist")

        return True, ""

    def _validate_set_property(self, op, scene, files, pending, pending_types) -> Tuple[bool, str]:
        node = op.get("node")
        prop = op.get("property")

        if not node or not prop:
            return False, "missing node or property"

        if not scene.has_path(node) and node not in pending:
            return False, f"node '{node}' not found"

        # Bug 1 fix (2026-06-14): validate property-vs-node-type.
        # A set_property on a type that can't hold that property (e.g.
        # material_override on a DirectionalLight3D) silently rolls back
        # the entire atomic batch_execute. Drop such ops here so the
        # valid ops in the batch still execute.
        node_type = pending_types.get(node)
        if node_type is None:
            node_type = self._lookup_node_type(scene, node)
        if node_type:
            allowed = _property_matches_type(prop, node_type)
            if allowed is False:
                return False, (
                    f"property '{prop}' not valid for {node_type} '{node}' — dropped to protect atomic batch"
                )

        return True, ""

    def _validate_connect_signal(self, op, scene, files, pending, pending_types) -> Tuple[bool, str]:
        source = op.get("source")
        target = op.get("target")
        signal = op.get("signal")
        method = op.get("method")

        if not all([source, target, signal, method]):
            return False, "missing source, target, signal, or method"

        if not scene.has_path(source) and source not in pending:
            return False, f"source '{source}' not found"
        if not scene.has_path(target) and target not in pending:
            return False, f"target '{target}' not found"

        return True, ""

    def _validate_add_child_scene(self, op, scene, files, pending, pending_types) -> Tuple[bool, str]:
        parent = op.get("parent")
        scene_path = op.get("scene")

        if not parent or not scene_path:
            return False, "missing parent or scene"

        if not scene.has_path(parent) and parent not in pending:
            return False, f"parent '{parent}' not found"

        return True, ""

    @staticmethod
    def _lookup_node_type(scene: SceneGraph, path: str) -> str | None:
        """Find the Godot type for *path* in the scene graph.

        Walks recursively from the root. Returns None if the node
        is not found or has no type field.
        """
        node = scene.find_by_path(path)
        if node is not None:
            return getattr(node, "type", None)
        return None
