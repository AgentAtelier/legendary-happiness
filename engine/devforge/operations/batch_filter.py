"""Batch filter — parse structured queries and match scene nodes.

Deterministic filter parsing (no LLM).  Supports two syntax forms:

    Structured (exact):          ``type:OmniLight3D name~lamp under:/root/Main``
    Convenience (regex-mapped):  ``"all OmniLight3Ds"``, ``"every Timer under /root/X"``,
                                 ``"nodes named foo"``

Tokens are space-separated.  Unknown tokens raise ``ValueError`` naming the
valid forms.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from devforge.knowledge.scene.scene_graph import SceneGraph
from typing import Any


@dataclass
class NodeFilter:
    """Filter criteria for batch node matching."""

    node_type: str | None = None    # exact Godot type, e.g. "OmniLight3D"
    name_contains: str | None = None  # case-insensitive substring
    under_path: str | None = None   # subtree root, e.g. "/root/Main/Enemies"


# ── Convenience phrase regexes ──────────────────────────────────
# Each maps a human-friendly phrase to structured tokens.  Keep these
# simple — they exist as a UX nicety, not as an LLM-parsing target.

_CONVENIENCE_PATTERNS: list[tuple[str, str]] = [
    # "all OmniLight3Ds" → type:OmniLight3D  (strip trailing 's')
    (r"^all\s+(\w+)s$", r"type:\1"),
    # "every Timer under /root/X" → type:Timer under:/root/X
    (
        r"^every\s+(\w+)\s+under\s+(/\S+)$",
        r"type:\1 under:\2",
    ),
    # "nodes named foo" → name~foo
    (r"^nodes\s+named\s+(.+)$", r"name~\1"),
]


def parse_query(query: str) -> NodeFilter:
    """Parse a user query string into a ``NodeFilter``.

    Accepts structured syntax (``type:X name~Y under:/path``) and a
    small set of convenience phrasings (``"all OmniLight3Ds"``, etc.).

    Raises ``ValueError`` when the query contains tokens that don't
    match any known form.
    """
    query = query.strip()
    if not query:
        raise ValueError(
            "Empty query — use structured syntax: "
            "type:NodeType name~substring under:/root/Path"
        )

    # Try convenience phrasings first
    for pattern, template in _CONVENIENCE_PATTERNS:
        m = re.match(pattern, query, re.IGNORECASE)
        if m:
            # Expand the template with captured groups
            query = re.sub(
                r"\\(\d)",
                lambda g: m.group(int(g.group(1))),
                template,
            )
            break

    # Parse tokenised structured syntax
    filter_kwargs: dict[str, str] = {}
    for token in query.split():
        if token.startswith("type:"):
            filter_kwargs["node_type"] = token[5:]
        elif token.startswith("name~"):
            filter_kwargs["name_contains"] = token[5:]
        elif token.startswith("under:"):
            filter_kwargs["under_path"] = token[6:]
        else:
            raise ValueError(
                f"Unknown token '{token}'. Valid forms: "
                f"type:<GodotType>  name~<substring>  under:<path>"
            )

    if not filter_kwargs:
        raise ValueError(
            "No filter criteria in query. Use: "
            "type:<GodotType>  name~<substring>  under:<path>"
        )

    return NodeFilter(**filter_kwargs)


def match_nodes(scene_tree: dict, f: NodeFilter) -> list[str]:
    """Return node paths matching *f* in *scene_tree*.

    Matching is deterministic and ordered by node path.  Type match is
    exact; name match is case-insensitive substring; ``under_path``
    means the node's path starts with ``under_path + \"/\"`` (or equals
    it).
    """
    graph = SceneGraph(scene_tree)
    matched: list[str] = []

    for node in graph.all_nodes():
        # Type filter: exact match
        if f.node_type is not None and node.type != f.node_type:
            continue

        # Name filter: case-insensitive substring
        if f.name_contains is not None:
            node_name = node.name or ""
            if f.name_contains.lower() not in node_name.lower():
                continue

        # Subtree filter: path prefix
        if f.under_path is not None:
            if not (
                node.path == f.under_path
                or node.path.startswith(f.under_path + "/")
            ):
                continue

        matched.append(node.path)

    # Stable ordering: sort by path
    matched.sort()
    return matched


def build_batch_ops(
    paths: list[str], property: str, value: Any
) -> list[dict]:
    """Build ``set_property`` operation dicts for matched node paths.

    Returns one operation per path, ordered the same as *paths*.
    """
    return [
        {
            "type": "set_property",
            "node": path,
            "property": property,
            "value": value,
        }
        for path in paths
    ]
