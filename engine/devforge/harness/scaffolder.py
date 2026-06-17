"""Test Harness — generate deterministic test scaffolds from GDScript signatures.

Parses function signatures from GDScript files and generates skeleton
test files that the user fills in with actual test logic.  No LLM calls
— the scaffolds are purely structural.

Deterministic core (tier 0).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ParsedFunc:
    """A single function parsed from a GDScript file."""

    name: str
    params: list[dict]  # [{"name": "a", "type": "int", "default": None}, ...]
    return_type: str = ""
    is_static: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "params": self.params,
            "return_type": self.return_type,
            "is_static": self.is_static,
        }


class TestScaffolder:
    """Parses GDScript signatures and generates test scaffold files.

    Usage::

        scaff = TestScaffolder()
        scaffold = scaff.generate("extends Node\nfunc add(a: int, b: int) -> int:\n    return a + b")
    """

    # Regex for GDScript function signatures:
    # func name(param: type = default, ...) -> return_type:
    _FUNC_RE = re.compile(
        r"func\s+(\w+)\s*\((.*?)\)\s*(?:->\s*(\w+))?\s*:",
        re.MULTILINE | re.DOTALL,
    )

    # Regex for parameters: name: type = default
    _PARAM_RE = re.compile(
        r"(\w+)\s*(?::\s*(\w+))?\s*(?:=\s*([^,)]+))?",
    )

    def parse(self, source: str) -> list[ParsedFunc]:
        """Extract function signatures from GDScript source code.

        Skips built-in methods (_ready, _process, _input, etc.) and
        private methods (prefixed with _).
        """
        funcs: list[ParsedFunc] = []
        for m in self._FUNC_RE.finditer(source):
            name = m.group(1)
            raw_params = m.group(2).strip()
            return_type = m.group(3) or ""

            # Parse parameters
            params: list[dict] = []
            if raw_params:
                for pm in self._PARAM_RE.finditer(raw_params):
                    params.append(
                        {
                            "name": pm.group(1),
                            "type": pm.group(2) or "Variant",
                            "default": pm.group(3),
                        }
                    )

            funcs.append(
                ParsedFunc(
                    name=name,
                    params=params,
                    return_type=return_type,
                    is_static=False,
                )
            )

        return funcs

    def public_functions(self, funcs: list[ParsedFunc]) -> list[ParsedFunc]:
        """Filter to public, testable functions only."""
        return [f for f in funcs if not f.name.startswith("_") and f.name not in ("static",)]

    def generate(
        self,
        source: str,
        script_path: str = "",
    ) -> dict:
        """Generate a test scaffold from GDScript source.

        Returns:
            {
              "script_path": "scripts/player.gd",
              "function_count": 5,
              "public_count": 2,
              "test_scaffold": "extends WAT\\n\\nfunc test_add():\\n    ...",
              "functions": [...ParsedFunc dicts...],
            }
        """
        funcs = self.parse(source)
        public = self.public_functions(funcs)
        test_source = self._build_test_source(public, script_path)

        return {
            "script_path": script_path,
            "function_count": len(funcs),
            "public_count": len(public),
            "test_scaffold": test_source,
            "functions": [f.to_dict() for f in public],
        }

    def _build_test_source(
        self,
        funcs: list[ParsedFunc],
        script_path: str,
    ) -> str:
        """Build a GDScript test file from parsed functions."""
        lines: list[str] = [
            "extends WAT",
            "",
        ]

        if script_path:
            lines.append(f'const TestScript = preload("res://{script_path.lstrip("res://")}")')
            lines.append("")

        for f in funcs:
            # Build parameter placeholders
            param_strs: list[str] = []
            for p in f.params:
                placeholder = self._param_placeholder(p)
                param_strs.append(placeholder)
            params_str = ", ".join(param_strs)

            lines.append("")
            lines.append(f"func test_{f.name}():")
            if f.return_type and f.return_type != "void":
                lines.append(f"\tvar result = TestScript.new().{f.name}({params_str})")
                lines.append(f"\t# TODO: assert result is the expected {f.return_type}")
            else:
                lines.append(f"\tTestScript.new().{f.name}({params_str})")
            lines.append("\t# TODO: add assertions")
            lines.append("\tassert(true)  # placeholder")

        lines.append("")
        return "\n".join(lines)

    def _param_placeholder(self, param: dict) -> str:
        """Generate a sensible default value for a parameter."""
        ptype = param.get("type", "Variant")
        if ptype in ("int", "float"):
            return "0"
        elif ptype == "bool":
            return "false"
        elif ptype == "String":
            return '"test"'
        elif ptype.startswith("Array"):
            return "[]"
        elif ptype.startswith("Dictionary"):
            return "{}"
        elif ptype == "Vector2":
            return "Vector2.ZERO"
        elif ptype == "Vector3":
            return "Vector3.ZERO"
        return "null"


def scaffold_file(filepath: str, source: str) -> dict:
    """Convenience wrapper: generate a scaffold from filepath + source."""
    scaff = TestScaffolder()
    return scaff.generate(source, filepath)
