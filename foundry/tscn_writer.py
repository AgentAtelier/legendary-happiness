"""foundry.tscn_writer — shared .tscn string-builders.

Pure functions (no I/O, no global state).  Every consumer imports the same
canonical primitives so both scene_compiler and exterior_compiler emit
byte-identical output from the same source.

See AGENTS.md § "Architecture orientation" and ROADMAP Phase 1.1.
"""

from __future__ import annotations


def fmt_float(v: float) -> str:
    """The canonical float formatter.  0.0 → '0', 1.0 → '1', 0.5 → '0.5'."""
    if v == int(v):
        return str(int(v))
    return str(v)


def ext_resource(type: str, path: str, id: str) -> str:
    """Return a single ``[ext_resource ...]`` header line (no uid)."""
    return f'[ext_resource type="{type}" path="{path}" id="{id}"]'


def sub_resource_header(type: str, id: str) -> str:
    """Return a ``[sub_resource ...]`` header line."""
    return f'[sub_resource type="{type}" id="{id}"]'


def node_header(
    name: str,
    type: str | None = None,
    parent: str | None = None,
    instance: str | None = None,
) -> str:
    """Return a ``[node ...]`` header line.

    When *instance* is given, ``instance=ExtResource(...)`` is written INSIDE
    the brackets (Godot 4 requires all node attributes inside ``[node ...]``;
    a trailing ``] instance=...`` does not parse).
    """
    parts: list[str] = [f'name="{name}"']
    if type is not None:
        parts.append(f'type="{type}"')
    if parent is not None:
        parts.append(f'parent="{parent}"')
    if instance is not None:
        parts.append(f'instance=ExtResource("{instance}")')
    return f"[node {' '.join(parts)}]"


def transform3d(
    basis: tuple[float, ...],
    origin: tuple[float, float, float],
) -> str:
    """Return a ``Transform3D(b00, ..., b22, ox, oy, oz)`` string.

    *basis* is 9 row-major elements; *origin* is translation xyz.
    Every element is formatted through :func:`fmt_float`.
    """
    vals = (
        [fmt_float(v) for v in basis]
        + [fmt_float(origin[0]), fmt_float(origin[1]), fmt_float(origin[2])]
    )
    return "Transform3D(" + ", ".join(vals) + ")"



