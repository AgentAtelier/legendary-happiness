"""Op translation — convert DevForge flat operations to godot-ai commands.

Pure functions (no state, no MCP dependency).  Extracted from
``godot_ai_mcp.py`` during the Phase 1A split.

The mapping tables were previously class-level attributes on
``GodotAIMCPExecutor``; they are now module-level constants here.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

# ── Operation type → godot-ai command mapping ─────────────────────
# batch_execute dispatches on the PLUGIN command names registered in
# godot-ai's plugin.gd dispatcher — NOT the MCP tool names (which are
# category-prefixed, e.g. the `script_attach` TOOL wraps the
# `attach_script` plugin command). Audited against plugin.gd June 2026.

OP_TO_COMMAND: dict[str, str] = {
    "add_node": "create_node",
    "set_property": "set_property",
    "attach_script": "attach_script",
    "connect_signal": "connect_signal",
    "remove_node": "delete_node",
    "rename_node": "rename_node",
}

# Field name remapping for the params dict. The plugin handlers read
# the target node from `path` (via _resolve_node / McpScenePath).
FIELD_MAP: dict[str, dict[str, str]] = {
    "add_node": {"parent": "parent_path", "node_type": "type", "scene_path": "scene_path"},
    "set_property": {"node": "path"},
    "attach_script": {"node": "path", "script": "script_path"},
    "connect_signal": {"source": "path"},
    "remove_node": {"node": "path"},
    "rename_node": {"node": "path"},
}

# Fields to drop from params (already consumed)
DROP_FIELDS: set[str] = {"type"}


# ── Translation ────────────────────────────────────────────────────


def translate_ops_to_commands(operations: List[Dict[str, Any]]) -> list[dict]:
    """Convert DevForge flat operations to godot-ai nested commands.

    DevForge generates flat dicts like::

        {"type": "add_node", "parent": "/root/Main",
         "node_type": "Camera3D", "name": "MainCamera"}

    godot-ai's ``batch_execute`` expects::

        {"command": "create_node",
         "params": {"parent_path": "/root/Main",
                   "type": "Camera3D", "name": "MainCamera"}}
    """
    from devforge.infrastructure.logger import logger

    commands: list[dict] = []
    for op in operations:
        op_type = op.get("type", "")
        command_name = OP_TO_COMMAND.get(op_type)
        if command_name is None:
            logger.warn(
                "executor.mcp",
                f"Unknown operation type '{op_type}' — skipping",
            )
            continue

        field_map = FIELD_MAP.get(op_type, {})
        params: dict[str, Any] = {}
        for key, value in op.items():
            if key in DROP_FIELDS:
                continue
            mapped_key = field_map.get(key, key)
            params[mapped_key] = value

        # godot-ai validates resource paths as res:// URIs
        if "script_path" in params:
            params["script_path"] = res_path(params["script_path"])

        commands.append({"command": command_name, "params": params})

    return commands


def res_path(path: str) -> str:
    """Normalize a project-relative path to the res:// form godot-ai
    requires (its path validator rejects anything else)."""
    if path.startswith("res://"):
        return path
    return f"res://{path.lstrip('/')}"


# ── Result parsing ─────────────────────────────────────────────────


def normalize_op_result(r: Any) -> Any:
    """Ensure a per-op batch result carries an explicit ``success`` bool.

    godot-ai's batch_execute reports per-command outcomes as
    ``{"command": ..., "status": "ok"|"error", ...}`` — it never sends
    a ``success`` key. ExecutionResult.success_count/failure_count
    require one, so without normalization every applied op counts as
    a failure while the overall result still says success.
    """
    if not isinstance(r, dict) or "success" in r:
        return r
    status = str(r.get("status", "")).lower()
    r["success"] = status in ("ok", "success") and "error" not in r
    return r


def parse_tool_result(result) -> Any:
    """Extract the value from an MCP tool call result.

    MCP results come as CallToolResult with a list of content blocks.
    We try JSON first, then plain text.
    """
    if result is None:
        return None

    # Result may have a .content attribute (list of TextContent blocks)
    content = getattr(result, "content", None)
    if content is None:
        return result

    if not content:
        return None

    # Single content block
    if len(content) == 1:
        text = getattr(content[0], "text", None)
        if text is not None:
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return text
        return content[0]

    # Multiple content blocks — try each
    texts = []
    for block in content:
        text = getattr(block, "text", None)
        if text is not None:
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                texts.append(text)

    return texts[0] if len(texts) == 1 else texts


def parse_tool_result_text(result) -> str | None:
    """Extract plain text from an MCP tool result."""
    text = parse_tool_result(result)
    if isinstance(text, str):
        return text
    if isinstance(text, (list, dict)):
        return json.dumps(text)
    return str(text) if text is not None else None


# ── Scene hierarchy unwrapping ────────────────────────────────────


def unwrap_scene_hierarchy(parsed: Any) -> Dict[str, Any] | None:
    """Extract the tree root from godot-ai's wrapped response.

    godot-ai's ``scene_get_hierarchy`` returns::

        {"root": "", "nodes": [...], "total_count": N, ...}

    Since at least 2.7.x the ``nodes`` list is FLAT — each entry has
    ``path`` and a numeric ``children_count`` but NO nested
    ``children`` array.  Taking ``nodes[0]`` as-is (the old behavior)
    handed the pipeline a bare root: the planner saw an empty scene,
    the validator validated against nothing, and the completeness
    checker re-injected Camera3D/DirectionalLight3D duplicates on
    every apply (observed live June 12, 2026).  Rebuild the nested
    tree from the paths instead.
    """
    if not isinstance(parsed, dict):
        return None
    nodes = parsed.get("nodes", [])
    if nodes and isinstance(nodes[0], dict):
        first = nodes[0]
        if "children" not in first and isinstance(first.get("path"), str):
            tree = tree_from_flat(nodes)
            if tree is not None:
                return tree
        return first
    root = parsed.get("root")
    if isinstance(root, dict):
        return root
    # Fallback: an unwrapped response that already IS the tree
    if "name" in parsed or "type" in parsed:
        return parsed
    return None


def tree_from_flat(nodes: list) -> Dict[str, Any] | None:
    """Rebuild a nested {name, type, children} tree from godot-ai's
    flat ``nodes`` list, linking children to parents via ``path``.
    Parents precede children in the walk order; entries whose parent
    falls outside the (possibly paginated/depth-limited) window attach
    to the root so no scanned node is silently dropped."""
    by_path: Dict[str, Dict[str, Any]] = {}
    root: Dict[str, Any] | None = None
    for n in nodes:
        if not isinstance(n, dict):
            continue
        path = n.get("path")
        if not isinstance(path, str) or not path:
            continue
        entry = {
            "name": n.get("name", ""),
            "type": n.get("type", ""),
            "children": [],
        }
        by_path[path] = entry
        parent_path = path.rsplit("/", 1)[0]
        parent = by_path.get(parent_path)
        if parent is not None:
            parent["children"].append(entry)
        elif root is None:
            root = entry
        else:
            root["children"].append(entry)
    return root
