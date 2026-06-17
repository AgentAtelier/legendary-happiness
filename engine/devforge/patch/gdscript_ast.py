"""
GDScript AST Parser — tree-sitter-gdscript wrapper with regex fallback.

Phase 8: Provides AST-level parsing for the deterministic validator rules.
When tree-sitter-gdscript is unavailable, gracefully falls back to
the old regex-based parsing (Tier 1 behaviour).

Usage:
    from devforge.patch.gdscript_ast import GdscriptParser

    parser = GdscriptParser()
    tree = parser.parse(content_bytes)

    # Check for class_name
    for node in parser.find_nodes(tree, "class_name_statement"):
        name = parser.get_child_text(node, "identifier")

    # Check for syntax errors
    errors = parser.collect_errors(tree)

    # Check function types
    for func in parser.iter_functions(tree):
        if func["return_type"] is None:
            print(f"Untyped return: {func['name']}")
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

# --------------------------------------------------------------------------
# Tree-sitter availability check
# --------------------------------------------------------------------------
_HAS_TREE_SITTER = False
_language = None
_Language = None
_Parser = None

try:
    import tree_sitter_gdscript._binding as _b
    from tree_sitter import Language as _Lang, Parser as _P

    _capsule = _b.language()
    _language = _Lang(_capsule)
    _Parser = _P
    _Language = _Lang
    _HAS_TREE_SITTER = True
except (ImportError, AttributeError, TypeError):
    _HAS_TREE_SITTER = False


# --------------------------------------------------------------------------
# Public types
# --------------------------------------------------------------------------
@dataclass
class FuncInfo:
    """Extracted function information from AST."""

    name: str
    line_number: int
    return_type: Optional[str]
    params: List[Dict[str, Any]] = field(default_factory=list)
    is_static: bool = False
    is_public: bool = True


@dataclass
class SyntaxError:
    """A syntax error found in the source."""

    line_number: int
    column: int
    message: str


# --------------------------------------------------------------------------
# Regex fallback patterns (Tier 1 — used when tree-sitter unavailable)
# --------------------------------------------------------------------------
_RE_FUNC_T1 = re.compile(
    r"(?:static\s+)?func\s+(?P<name>\w+)\s*"
    r"\((?P<params>[^)]*)\)\s*"
    r"(?:->\s*(?P<ret>[^:]+?))?\s*:"
)
_RE_PARAM_T1 = re.compile(r"(\w+)(?:\s*:\s*(\S+(?:\s*\[[^\]]*\])?))?(?:\s*=.*)?")
_RE_CLASS_NAME_T1 = re.compile(r"class_name\s+(\w+)")


def _t1_find_funcs(content: str) -> List[FuncInfo]:
    """Tier 1 regex fallback for function extraction."""
    funcs: List[FuncInfo] = []
    # Strip strings to avoid matching func inside strings
    stripped = _t1_strip_strings(content)
    for line_num, line in enumerate(stripped.splitlines(), start=1):
        m = _RE_FUNC_T1.search(line)
        if not m:
            continue
        name = m.group("name")
        ret = m.group("ret")
        f = FuncInfo(
            name=name,
            line_number=line_num,
            return_type=ret.strip() if ret else None,
            params=[],
            is_static="static" in line[: m.start() + 10],
            is_public=not name.startswith("_"),
        )
        # Parse params
        params_str = m.group("params") or ""
        if params_str.strip():
            for param in _t1_split_params(params_str):
                pm = _RE_PARAM_T1.match(param.strip())
                if pm:
                    f.params.append(
                        {
                            "name": pm.group(1),
                            "type": pm.group(2),
                        }
                    )
        funcs.append(f)
    return funcs


def _t1_split_params(params: str) -> List[str]:
    """Split parameter string by comma, respecting nested generics."""
    result = []
    depth = 0
    current = ""
    for ch in params:
        if ch in "([":
            depth += 1
            current += ch
        elif ch in ")]":
            depth -= 1
            current += ch
        elif ch == "," and depth == 0:
            result.append(current)
            current = ""
        else:
            current += ch
    if current.strip():
        result.append(current)
    return result


def _t1_strip_strings(text: str) -> str:
    """Replace string literals with spaces for pattern matching (Tier 1)."""
    result = []
    i = 0
    while i < len(text):
        ch = text[i]
        # Triple-quoted strings
        if text[i : i + 3] in ('"""', "'''"):
            delim = text[i : i + 3]
            i += 3
            end = text.find(delim, i)
            i = end + 3 if end != -1 else len(text)
            continue
        # Regular strings
        if ch in ('"', "'"):
            quote = ch
            i += 1
            while i < len(text):
                if text[i] == "\\" and i + 1 < len(text):
                    i += 2
                    continue
                if text[i] == quote:
                    result.append(" ")
                    i += 1
                    break
                i += 1
            continue
        # Comments
        if ch == "#":
            nl = text.find("\n", i)
            i = nl + 1 if nl != -1 else len(text)
            continue
        result.append(ch)
        i += 1
    return "".join(result)


# --------------------------------------------------------------------------
# Main parser class
# --------------------------------------------------------------------------
class GdscriptParser:
    """AST parser for GDScript files using tree-sitter-gdscript.

    Falls back to regex (Tier 1) when the grammar is unavailable.
    """

    def __init__(self) -> None:
        self._parser = None
        if _HAS_TREE_SITTER and _language is not None:
            self._parser = _Parser(_language)

    # ------------------------------------------------------------------
    # Property
    # ------------------------------------------------------------------
    @property
    def has_ast(self) -> bool:
        """Whether tree-sitter AST parsing is available."""
        return self._parser is not None

    # ------------------------------------------------------------------
    # Parse
    # ------------------------------------------------------------------
    def parse(self, content: str) -> Any:
        """Parse GDScript content and return the root AST node.

        Returns a tree-sitter Node when available, or None when using regex fallback.
        Callers should check ``has_ast`` before calling AST-specific methods.
        """
        if self._parser is not None:
            return self._parser.parse(content.encode("utf-8")).root_node
        return None

    # ------------------------------------------------------------------
    # Node discovery
    # ------------------------------------------------------------------
    def find_nodes(self, root: Any, node_type: str) -> List[Any]:
        """Find all descendant nodes matching *node_type*."""
        if root is None:
            return []
        nodes: List[Any] = []
        self._collect_by_type(root, node_type, nodes)
        return nodes

    def _collect_by_type(self, node: Any, node_type: str, out: List[Any]) -> None:
        if node.type == node_type:
            out.append(node)
        for child in node.children:
            self._collect_by_type(child, node_type, out)

    def get_child_text(self, node: Any, child_type: str) -> Optional[str]:
        """Get the decoded text of the first child matching *child_type*."""
        for child in node.children:
            if child.type == child_type:
                return child.text.decode("utf-8")
        return None

    def has_child(self, node: Any, child_type: str) -> bool:
        """Check if the node has a direct child of the given type."""
        for child in node.children:
            if child.type == child_type:
                return True
        return False

    def get_children_of_type(self, node: Any, child_type: str) -> List[Any]:
        """Return all direct children of the given type."""
        return [c for c in node.children if c.type == child_type]

    # ------------------------------------------------------------------
    # R3: Class name
    # ------------------------------------------------------------------
    def get_class_name(self, content: str) -> Optional[Tuple[str, int]]:
        """Return (class_name, line_number) if declared, else None."""
        if self._parser is not None:
            root = self.parse(content)
            nodes = self.find_nodes(root, "class_name_statement")
            if nodes:
                node = nodes[0]
                name = self.get_child_text(node, "identifier")
                if name:
                    line = node.start_point[0] + 1
                    return (name, line)
            return None
        else:
            # Tier 1 fallback
            for line_num, line in enumerate(content.splitlines(), start=1):
                m = _RE_CLASS_NAME_T1.search(line)
                if m:
                    return (m.group(1), line_num)
            return None

    # ------------------------------------------------------------------
    # R4: Syntax errors
    # ------------------------------------------------------------------
    def collect_errors(self, root: Any) -> List[SyntaxError]:
        """Collect all ERROR nodes from the AST (tree-sitter mode).

        In regex mode, returns an empty list — R4 falls back to
        brace/paren counting (old Tier 1 behaviour).
        """
        if root is None:
            return []
        errors: List[SyntaxError] = []
        self._collect_errors(root, errors)
        return errors

    def _collect_errors(self, node: Any, out: List[SyntaxError]) -> None:
        if node.type == "ERROR":
            sp = node.start_point
            out.append(
                SyntaxError(
                    line_number=sp[0] + 1,
                    column=sp[1] + 1,
                    message=f"Parse error: {node.text.decode('utf-8', errors='replace')[:120]}",
                )
            )
        for child in node.children:
            self._collect_errors(child, out)

    # ------------------------------------------------------------------
    # R5: Function extraction
    # ------------------------------------------------------------------
    def iter_functions(self, content: str) -> Iterable[FuncInfo]:
        """Yield FuncInfo for every function definition.

        Uses AST when available (supports multiline signatures),
        falls back to regex (Tier 1, same-line only).
        """
        if self._parser is not None:
            root = self.parse(content)
            for func_node in self.find_nodes(root, "function_definition"):
                yield self._extract_func_info(func_node)
        else:
            yield from _t1_find_funcs(content)

    def _extract_func_info(self, node: Any) -> FuncInfo:
        """Extract function info from a function_definition AST node."""
        name = self.get_child_text(node, "name") or ""
        line = node.start_point[0] + 1
        is_static = self.has_child(node, "static_keyword")
        return_type = None

        # Check for return type annotation
        for child in node.children:
            if child.type == "return_type":
                # return_type contains a type_annotation child
                for tc in child.children:
                    if tc.type == "type_annotation" and tc.child_count > 0:
                        return_type = tc.text.decode("utf-8").strip()
                        break
                break

        params: List[Dict[str, Any]] = []
        for pnode in self.get_children_of_type(node, "typed_parameter"):
            pname = self.get_child_text(pnode, "identifier")
            ptype = None
            for pc in pnode.children:
                if pc.type == "type_annotation" and pc.child_count > 0:
                    ptype = pc.text.decode("utf-8").strip()
                    break
            if pname:
                params.append({"name": pname, "type": ptype})

        return FuncInfo(
            name=name,
            line_number=line,
            return_type=return_type,
            params=params,
            is_static=is_static,
            is_public=not name.startswith("_"),
        )

    # ------------------------------------------------------------------
    # R6: node safety — get_node() with string literals
    # ------------------------------------------------------------------
    def find_get_node_violations(self, root: Any) -> List[Tuple[int, str]]:
        """Find get_node(\"...\") calls with string literal arguments.

        Returns list of (line_number, message).
        """
        if root is None:
            return []
        violations: List[Tuple[int, str]] = []
        for call_node in self.find_nodes(root, "call"):
            # Check if the call's function name is get_node
            name = self.get_child_text(call_node, "identifier")
            if name == "get_node":
                for arg_node in call_node.children:
                    if arg_node.type == "arguments":
                        for child in arg_node.children:
                            if child.type == "string":
                                line = child.start_point[0] + 1
                                violations.append(
                                    (
                                        line,
                                        "get_node() with string literal detected — "
                                        "use $NodePath notation or @onready var instead",
                                    )
                                )
        return violations
