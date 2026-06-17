"""Template Engine — load, list, preview, and instantiate templates.

Deterministic core (tier 0): no LLM calls in this module.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable

from devforge.forge.template_ir import (
    Template,
    resolve_slot_values,
    substitute_operations,
    substitute_slots,
    template_from_dict,
)
from devforge.infrastructure.logger import logger
from devforge.execution.interface import Executor


# Default template directory (relative to project root)
DEFAULT_TEMPLATE_DIR = "devforge/forge/templates"


def list_templates(directory: str | None = None) -> list[dict]:
    """Scan *directory* for ``.template.json`` files.

    Returns a list of summary dicts (slug, name, description,
    slot_count, script_count) sorted by name.  No slot resolution
    or LLM interaction — pure filesystem scan.
    """
    directory = directory or DEFAULT_TEMPLATE_DIR
    path = Path(directory)
    if not path.is_dir():
        logger.warn("template_engine", f"Template directory not found: {directory}")
        return []

    templates: list[dict] = []
    for f in sorted(path.glob("*.template.json")):
        try:
            t = _load_template_file(str(f))
            templates.append(
                {
                    "slug": t.slug,
                    "name": t.name,
                    "description": t.description,
                    "slot_count": len(t.slots),
                    "script_count": len(t.scripts),
                }
            )
        except Exception as exc:
            logger.warn(
                "template_engine",
                f"Skipping {f.name}: {exc}",
            )

    return sorted(templates, key=lambda t: t["name"])


def load_template(slug: str, directory: str | None = None) -> Template | None:
    """Load a template by slug from disk.

    Returns None if the template file doesn't exist or can't be parsed.
    """
    directory = directory or DEFAULT_TEMPLATE_DIR
    filepath = os.path.join(directory, f"{slug}.template.json")
    try:
        return _load_template_file(filepath)
    except Exception as exc:
        logger.warn(
            "template_engine",
            f"Failed to load template '{slug}': {exc}",
        )
        return None


_INPUT_ACTION_RE = re.compile(
    r"""Input\.(?:is_action_(?:pressed|just_pressed|just_released)|get_action_strength)\(\s*"([^"]+)"\s*\)"""
)
_INPUT_VECTOR_RE = re.compile(
    r"""Input\.get_vector\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)"""
)
# Actions every fresh Godot project already has
_BUILTIN_ACTION_PREFIX = "ui_"


def required_input_actions(template: Template) -> list[str]:
    """Input Map actions a template's scripts depend on.

    A fresh Godot project only defines ``ui_*`` actions — a template
    referencing ``sprint`` or ``move_left`` will apply cleanly and then
    silently do nothing until the user adds those actions. Surfacing
    them turns a confusing dead controller into a checklist item.
    """
    actions: set[str] = set()
    for s in template.scripts:
        actions.update(_INPUT_ACTION_RE.findall(s.content))
        for group in _INPUT_VECTOR_RE.findall(s.content):
            actions.update(group)
    return sorted(a for a in actions if not a.startswith(_BUILTIN_ACTION_PREFIX))


def preview_template(
    template: Template,
    slot_values: dict[str, Any] | None,
    parent_path: str = "/root/Main",
) -> dict:
    """Resolve slots and return a preview of what would be created.

    Returns:
        {
          "slug": "fps_controller",
          "name": "FPS Controller",
          "parent_path": "/root/Main",
          "slot_values": {"camera_height": 1.7, ...},
          "script_count": 4,
          "operation_count": 12,
          "operations": [...],
          "script_previews": [{"path": "...", "content_preview": "..."}],
          "collision_check": ["/root/Main/Player"],
        }

    The preview is read-only — no scene mutation.
    """
    resolved = resolve_slot_values(template.slots, slot_values)
    ops = substitute_operations(template.operations, resolved)
    parent_scoped_ops = _scope_to_parent(ops, parent_path)

    script_previews: list[dict] = []
    for s in template.scripts:
        script_previews.append(
            {
                "path": s.path,
                "content_preview": substitute_slots(s.content, resolved)[:200] + "..."
                if len(s.content) > 200
                else substitute_slots(s.content, resolved),
            }
        )

    collision_scoped = [_scope_path(cp, parent_path) for cp in template.collision_check]

    return {
        "slug": template.slug,
        "name": template.name,
        "parent_path": parent_path,
        "slot_values": resolved,
        "script_count": len(template.scripts),
        "operation_count": len(ops),
        "operations": parent_scoped_ops,
        "script_previews": script_previews,
        "collision_check": collision_scoped,
        "required_input_actions": required_input_actions(template),
    }


def _refusal(errors: list[str], op_count: int) -> dict:
    """ExecutionResult-shaped refusal (nothing was executed)."""
    return {
        "success": False,
        "applied_count": 0,
        "errors": errors,
        "results": [],
        "success_count": 0,
        "failure_count": op_count,
    }


def instantiate_template(
    template: Template,
    slot_values: dict[str, Any] | None,
    parent_path: str,
    executor: Executor,
    existing_paths: set[str] | None = None,
    file_exists: "Callable[[str], bool | None] | None" = None,
    overwrite_files: bool = False,
) -> dict:
    """Resolve slots, check collisions, and execute via *executor*.

    *file_exists* checks whether a project-relative script path already
    exists in the Godot project (True/False, or None when undeterminable).
    godot-ai's script_create silently OVERWRITES existing files, so
    unless *overwrite_files* is True this function refuses to execute
    when any template script already exists — or when existence can't
    be verified. A user's customized script must never be destroyed by
    a re-applied template.

    Returns an ExecutionResult-like dict with applied_count and errors.
    """
    resolved = resolve_slot_values(template.slots, slot_values)
    ops = substitute_operations(template.operations, resolved)
    parent_scoped_ops = _scope_to_parent(ops, parent_path)

    # Collision check
    existing = existing_paths or set()
    collisions: list[str] = []
    for cp in template.collision_check:
        scoped = _scope_path(cp, parent_path)
        if scoped in existing:
            collisions.append(scoped)

    if collisions:
        return _refusal(
            [
                f"Collision: path(s) already exist: {', '.join(collisions)}. "
                f"Use a different parent_path or remove the existing nodes first."
            ],
            len(ops),
        )

    # Build files from substituted scripts
    files: list[dict] = []
    for s in template.scripts:
        files.append(
            {
                "path": s.path,
                "content": substitute_slots(s.content, resolved),
            }
        )

    # File-overwrite protection (safe by default)
    if files and not overwrite_files and file_exists is not None:
        clobbered: list[str] = []
        unverifiable: list[str] = []
        for f in files:
            status = file_exists(f["path"])
            if status is True:
                clobbered.append(f["path"])
            elif status is None:
                unverifiable.append(f["path"])
        if clobbered:
            return _refusal(
                [
                    f"Refusing to overwrite existing script(s): "
                    f"{', '.join(clobbered)}. Pass overwrite_files=true to "
                    f"replace them (this destroys any customizations)."
                ],
                len(ops),
            )
        if unverifiable:
            return _refusal(
                [
                    f"Could not verify whether these scripts already exist: "
                    f"{', '.join(unverifiable)}. Pass overwrite_files=true to "
                    f"proceed anyway (existing files would be replaced)."
                ],
                len(ops),
            )

    # Execute
    from devforge.execution.interface import ExecutionResult

    try:
        exec_result: ExecutionResult = executor.execute(
            parent_scoped_ops,
            files,
            None,
        )
        result_dict = exec_result.to_dict()
        result_dict["applied_count"] = result_dict.get("success_count", 0)
        needed_actions = required_input_actions(template)
        if needed_actions:
            result_dict["required_input_actions"] = needed_actions
            result_dict["hint"] = (
                "This system reads Input Map actions that fresh Godot "
                f"projects don't define: {', '.join(needed_actions)}. "
                "Add them in Project Settings → Input Map (or via "
                "godot-ai's input_map_manage) or the scripts will "
                "silently do nothing."
            )
        return result_dict
    except Exception as exc:
        return {
            "success": False,
            "applied_count": 0,
            "errors": [f"Template instantiation failed: {exc}"],
            "results": [],
            "success_count": 0,
            "failure_count": len(parent_scoped_ops),
        }


# ── Helpers ─────────────────────────────────────────────────────


def _load_template_file(filepath: str) -> Template:
    """Load and parse a single .template.json file."""
    with open(filepath, "r") as f:
        data = json.load(f)
    return template_from_dict(data)


def _scope_to_parent(ops: list[dict], parent_path: str) -> list[dict]:
    """Rewrite ``parent`` and ``node`` fields in operations to be
    relative to *parent_path*.  Ops with absolute paths (starting with
    ``/root``) are left unchanged; ops with relative paths are scoped.

    Always runs the full loop — templates may mix absolute and relative
    paths, and the absolute-path check is per-op, not per-call."""
    scoped = []
    for op in ops:
        op_copy = dict(op)
        # Rewrite the parent field in add_node operations
        if op.get("type") == "add_node" and "parent" in op_copy:
            raw_parent = op_copy["parent"]
            if not raw_parent.startswith("/root"):
                op_copy["parent"] = f"{parent_path.rstrip('/')}/{raw_parent.lstrip('/')}"
        # Rewrite node targets in set_property, attach_script, etc.
        if "node" in op_copy:
            raw_node = op_copy["node"]
            if not raw_node.startswith("/root"):
                op_copy["node"] = f"{parent_path.rstrip('/')}/{raw_node.lstrip('/')}"
        scoped.append(op_copy)
    return scoped


def _scope_path(template_path: str, parent_path: str) -> str:
    """Scope a template-relative path under *parent_path*."""
    if template_path.startswith("/root"):
        return template_path
    return f"{parent_path.rstrip('/')}/{template_path.lstrip('/')}"
