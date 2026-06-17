"""R4: Syntax Sanity — AST-level parse error detection.

Phase 8 (AST): Swapped from regex brace/paren counting to tree-sitter-gdscript
ERROR node detection. Tree-sitter's parse is authoritative — any ERROR node
in the AST means the code is syntactically invalid.

When tree-sitter is unavailable, falls back to Tier 1 regex brace/paren counting.
"""

from __future__ import annotations

from typing import List

from devforge.patch.gdscript_ast import GdscriptParser
from devforge.validation.rules.base import Rule, Violation

_parser = GdscriptParser()


class R4SyntaxSanity(Rule):
    """Check for GDScript syntax errors using tree-sitter AST."""

    def check(self, file_path: str, content: str) -> List[Violation]:
        violations: List[Violation] = []

        if _parser.has_ast:
            root = _parser.parse(content)
            errors = _parser.collect_errors(root)
            for err in errors:
                violations.append(
                    Violation(
                        rule_id="R4_SYNTAX_SANITY",
                        message=f"Syntax error: {err.message}",
                        line_number=err.line_number,
                        severity="critical",
                        action="block_merge",
                    )
                )
        else:
            # Tier 1 fallback: brace/paren counting + quote check
            violations.extend(self._t1_brace_check(content))
            violations.extend(_t1_quote_check(content))

        return violations

    @staticmethod
    def _t1_brace_check(content: str) -> List[Violation]:
        """Tier 1 fallback: regex-based brace/paren counting."""
        violations: List[Violation] = []

        # Strip strings and comments for brace/paren counting
        stripped = _t1_strip_content(content)

        # Balanced parentheses
        paren_depth = 0
        for ch in stripped:
            if ch == "(":
                paren_depth += 1
            elif ch == ")":
                paren_depth -= 1
            if paren_depth < 0:
                violations.append(
                    Violation(
                        rule_id="R4_SYNTAX_SANITY",
                        message="Unbalanced parentheses — extra closing ')'",
                        severity="critical",
                        action="block_merge",
                    )
                )
                break

        if paren_depth > 0 and not violations:
            violations.append(
                Violation(
                    rule_id="R4_SYNTAX_SANITY",
                    message=f"Unbalanced parentheses — {paren_depth} unclosed '('",
                    severity="critical",
                    action="block_merge",
                )
            )

        # Balanced braces
        brace_depth = 0
        for ch in stripped:
            if ch == "{":
                brace_depth += 1
            elif ch == "}":
                brace_depth -= 1
            if brace_depth < 0:
                violations.append(
                    Violation(
                        rule_id="R4_SYNTAX_SANITY",
                        message="Unbalanced braces — extra closing '}'",
                        severity="critical",
                        action="block_merge",
                    )
                )
                break

        if brace_depth > 0:
            violations.append(
                Violation(
                    rule_id="R4_SYNTAX_SANITY",
                    message=f"Unbalanced braces — {brace_depth} unclosed '{{'",
                    severity="critical",
                    action="block_merge",
                )
            )

        return violations


# --------------------------------------------------------------------------
# Tier 1 fallback helpers
# --------------------------------------------------------------------------
# _strip_strings imported from devforge.patch.gdscript_ast above


def _t1_quote_check(content: str) -> List[Violation]:
    """Check for unclosed quotes on non-comment lines.

    Only used in Tier 1 fallback since tree-sitter catches these
    via ERROR nodes with greater precision.
    """
    violations: List[Violation] = []
    for line_num, line in enumerate(content.splitlines(), start=1):
        cleaned = Rule.strip_comment(line)
        dq_count = cleaned.count('"')
        if dq_count % 2 != 0:
            violations.append(
                Violation(
                    rule_id="R4_SYNTAX_SANITY",
                    message="Trailing unclosed double-quote",
                    line_number=line_num,
                    severity="critical",
                    action="block_merge",
                )
            )
    return violations


def _t1_strip_content(text: str) -> str:
    """Remove string literals and comments for brace/paren counting.

    This is a local Tier 1 helper — the tree-sitter path doesn't need it.
    """
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
