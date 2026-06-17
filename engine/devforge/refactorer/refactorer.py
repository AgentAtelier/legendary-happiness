"""Scene Refactorer — extract a subtree from a scene into its own .tscn file.

Deterministic core (tier 0): no LLM calls. Takes a scene tree and a target
node path, extracts the subtree, and replaces it with an instance reference.
Pure Python tree manipulation — no godot-ai needed.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from devforge.infrastructure.logger import logger


@dataclass
class RefactorResult:
    """Result of a scene refactoring operation."""

    success: bool
    extracted_node_path: str          # "/root/Main/Enemies"
    new_instance_name: str            # "Enemies" (or "Enemies_001" if collision)
    extracted_scene_path: str         # "res://scenes/extracted_enemies.tscn"
    operations: list[dict] = field(default_factory=list)  # ops to apply
    warnings: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "extracted_node_path": self.extracted_node_path,
            "new_instance_name": self.new_instance_name,
            "extracted_scene_path": self.extracted_scene_path,
            "operation_count": len(self.operations),
            "operations": self.operations,
            "warnings": self.warnings,
            "error": self.error or None,
        }


class SceneRefactorer:
    """Extracts subtrees from a scene tree and replaces them with instances.

    Usage::

        refactorer = SceneRefactorer()
        result = refactorer.extract_subtree(
            scene_dict, "/root/Main/Enemies",
            output_path="res://scenes/enemies.tscn"
        )
    """

    def extract_subtree(
        self,
        scene: dict,
        node_path: str,
        output_path: str,
        *,
        collision_strategy: str = "rename",  # "rename" | "error" | "skip"
    ) -> RefactorResult:
        """Extract the subtree at *node_path* and replace it with an instance.

        Returns a RefactorResult with the operations needed to:
        1. Remove the subtree from the parent scene
        2. Add an instance reference in its place
        3. The extracted subtree becomes its own .tscn

        *collision_strategy*: what to do if a node with the same name exists:
          - "rename": append _001, _002, etc.
          - "error": return failure
          - "skip": return empty operations
        """
        if not node_path.startswith("/"):
            return RefactorResult(
                success=False,
                extracted_node_path=node_path,
                new_instance_name="",
                extracted_scene_path=output_path,
                error=f"node_path must start with '/', got '{node_path}'",
            )

        # Find the target node in the tree
        target, parent, _ = self._find_node(scene, node_path)
        if target is None:
            return RefactorResult(
                success=False,
                extracted_node_path=node_path,
                new_instance_name="",
                extracted_scene_path=output_path,
                error=f"Node not found: '{node_path}'",
            )

        node_name = target.get("name", "Unnamed")
        instance_name = node_name

        # Collision check
        if parent:
            sibling_names = {c.get("name", "") for c in parent.get("children", [])
                           if c is not target}
            if node_name in sibling_names:
                if collision_strategy == "error":
                    return RefactorResult(
                        success=False,
                        extracted_node_path=node_path,
                        new_instance_name=node_name,
                        extracted_scene_path=output_path,
                        error=f"Node name collision: '{node_name}' already exists at this level",
                    )
                elif collision_strategy == "skip":
                    return RefactorResult(
                        success=True,
                        extracted_node_path=node_path,
                        new_instance_name=instance_name,
                        extracted_scene_path=output_path,
                        operations=[],
                        warnings=["Node already exists — skipping"],
                    )
                else:  # rename
                    counter = 1
                    while f"{node_name}_{counter:03d}" in sibling_names:
                        counter += 1
                    instance_name = f"{node_name}_{counter:03d}"

        # Build operations
        ops: list[dict] = []

        # 1. Save the extracted subtree as a separate scene
        # (This is informational — the actual file write is separate)
        extracted = copy.deepcopy(target)
        # Remove parent references from extracted node
        if extracted.get("parent"):
            del extracted["parent"]

        # 2. Remove the original node
        ops.append({"type": "remove_node", "node": node_path})

        # 3. Add instance reference
        parent_path = node_path.rsplit("/", 1)[0] or "/root"

        ops.append({
            "type": "add_node",
            "parent": parent_path,
            "node_type": "instance",
            "name": instance_name,
            "instance_path": output_path,
        })

        logger.info(
            "refactorer",
            f"Extracted '{node_path}' → '{output_path}' as '{instance_name}'",
        )

        return RefactorResult(
            success=True,
            extracted_node_path=node_path,
            new_instance_name=instance_name,
            extracted_scene_path=output_path,
            operations=ops,
        )

    def _find_node(
        self,
        node: dict,
        path: str,
        parent: dict | None = None,
        current_path: str = "",
    ) -> tuple[dict | None, dict | None, str]:
        """Walk the tree to find the node at *path*.

        Returns (node_dict, parent_dict, resolved_path).
        """
        name = node.get("name", "")
        node_path = f"{current_path}/{name}" if current_path else f"/{name}"

        if node_path == path or f"/{name}" == path:
            return node, parent, node_path

        for child in node.get("children", []):
            result = self._find_node(child, path, node, node_path)
            if result[0] is not None:
                return result

        return None, None, ""

    def list_extractable_subtrees(
        self,
        scene: dict,
        min_children: int = 3,
    ) -> list[dict]:
        """List all subtrees suitable for extraction (nodes with >= *min_children* children)."""
        candidates: list[dict] = []

        def _walk(node: dict, path: str):
            children = node.get("children", [])
            if len(children) >= min_children:
                candidates.append({
                    "path": path,
                    "name": node.get("name", ""),
                    "type": node.get("type", ""),
                    "child_count": len(children),
                    "suggested_output": f"res://scenes/extracted_{node.get('name', 'unnamed').lower()}.tscn",
                })
            for i, child in enumerate(children):
                _walk(child, f"{path}/{child.get('name', f'child_{i}')}")

        _walk(scene, f"/{scene.get('name', 'root')}")
        return candidates


def extract_subtree(
    scene: dict,
    node_path: str,
    output_path: str,
    collision_strategy: str = "rename",
) -> dict:
    """Convenience wrapper: extract a subtree and return result dict."""
    refactorer = SceneRefactorer()
    result = refactorer.extract_subtree(scene, node_path, output_path, collision_strategy=collision_strategy)
    return result.to_dict()


def list_extractable(scene: dict, min_children: int = 3) -> dict:
    """Convenience wrapper: list extractable subtrees."""
    refactorer = SceneRefactorer()
    candidates = refactorer.list_extractable_subtrees(scene, min_children)
    return {
        "candidate_count": len(candidates),
        "candidates": candidates,
        "hint": f"Found {len(candidates)} extractable subtrees with >= {min_children} children.",
    }
