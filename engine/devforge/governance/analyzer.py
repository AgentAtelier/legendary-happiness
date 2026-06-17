"""
DevForge GDScript Static Analyzer
===================================
Two-pass structural analyzer for GDScript 4.x files.

Pass 1 (Preprocessing):
    - Strip comments and multiline strings
    - Join multiline signatures (unclosed parentheses)
    - Produce clean logical lines with original line numbers

Pass 2 (Extraction):
    - Track scope via indentation (top-level, inner class, function body)
    - Extract imports, functions, variables, signals, class structure
    - Flag unparseable constructs explicitly (never silently skip)

Design constraints:
    - This is NOT a full AST parser. It extracts the specific structural
      information Gate 1 needs: imports, public method signatures, return types.
    - When it encounters a construct it cannot parse, it emits a ParseWarning
      rather than silently skipping. Gate 1 can then flag these for manual review.
    - Handles: multiline func signatures, inner classes, typed arrays/dicts,
      static functions, @annotations, complex preload chains.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set, Tuple

from devforge.infrastructure.logger import logger


# --------------------------------------------------------------------------
# Data structures
# --------------------------------------------------------------------------
@dataclass
class ParseWarning:
    """Emitted when the analyzer encounters something it cannot fully parse."""
    line_number: int
    category: str       # "multiline", "complex_type", "nested_scope", "syntax"
    raw_line: str
    message: str


@dataclass
class GDImport:
    """A reference to another file via preload(), load(), or extends."""
    kind: str           # "preload", "load", or "extends"
    path: str           # The referenced path (may be res:// prefixed)
    line_number: int
    raw_line: str


@dataclass
class GDFunction:
    """A function/method declaration."""
    name: str
    is_public: bool
    return_type: Optional[str]
    param_types: List[str]
    line_number: int
    raw_line: str
    is_static: bool = False
    scope: str = "top"          # "top" or "inner:ClassName"
    has_parse_warning: bool = False


@dataclass
class GDSignal:
    """A signal declaration."""
    name: str
    line_number: int
    parameters: List[str] = field(default_factory=list)


@dataclass
class GDVariable:
    """A variable or constant declaration."""
    name: str
    kind: str           # "var", "const", "@onready var", "@export var"
    type_hint: Optional[str]
    value_path: Optional[str]   # If assigned via preload/load
    line_number: int


@dataclass
class GDInnerClass:
    """An inner class declaration."""
    name: str
    extends: Optional[str]
    line_number: int
    indent_level: int


@dataclass
class GDFileAnalysis:
    """Complete structural analysis of a single GDScript file."""
    file_path: str
    class_name: Optional[str] = None
    extends: Optional[str] = None
    extends_path: Optional[str] = None
    imports: List[GDImport] = field(default_factory=list)
    functions: List[GDFunction] = field(default_factory=list)
    signals: List[GDSignal] = field(default_factory=list)
    variables: List[GDVariable] = field(default_factory=list)
    inner_classes: List[GDInnerClass] = field(default_factory=list)
    warnings: List[ParseWarning] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def public_functions(self) -> List[GDFunction]:
        return [f for f in self.functions if f.is_public]

    @property
    def import_paths(self) -> Set[str]:
        paths = {imp.path for imp in self.imports}
        if self.extends_path:
            paths.add(self.extends_path)
        return paths

    @property
    def has_unparsed_constructs(self) -> bool:
        return len(self.warnings) > 0


# --------------------------------------------------------------------------
# Pass 1: Preprocessing — clean lines with multiline joining
# --------------------------------------------------------------------------
@dataclass
class LogicalLine:
    """A logical line after preprocessing (may span multiple raw lines)."""
    text: str
    start_line: int
    end_line: int
    indent: int         # Number of leading tabs (GDScript standard indent)
    raw: str            # Original text for error reporting


def _preprocess(lines: List[str]) -> Tuple[List[LogicalLine], List[ParseWarning]]:
    """
    Preprocess raw file lines into logical lines.

    Handles:
        - Stripping comments (# to end of line, outside strings)
        - Skipping multiline strings (triple-quoted)
        - Joining multiline signatures (unclosed parentheses)
    """
    logical_lines: List[LogicalLine] = []
    warnings: List[ParseWarning] = []

    in_multiline_string = False

    # Accumulator for multiline joins
    join_buffer = ""
    join_start_line = 0
    join_raw = ""
    paren_depth = 0

    i = 0
    while i < len(lines):
        line_num = i + 1
        raw = lines[i].rstrip("\n\r")
        i += 1

        # --- Multiline string tracking ---
        if in_multiline_string:
            if '"""' in raw or "'''" in raw:
                in_multiline_string = False
            continue

        # Count triple-quote toggles (handle both \"\"\" and ''')
        dq_count = raw.count('"""')
        sq_count = raw.count("'''")
        total_toggles = dq_count + sq_count
        if total_toggles % 2 == 1:
            if not in_multiline_string:
                in_multiline_string = True
                continue
            else:
                in_multiline_string = False
                continue

        # --- Strip inline comments ---
        code = _strip_inline_comment(raw)

        if not code.strip():
            continue

        # --- Calculate indent ---
        indent = 0
        for ch in code:
            if ch == "\t":
                indent += 1
            elif ch == " ":
                indent += 1  # Count spaces too, normalize later
            else:
                break

        # --- Multiline join (unclosed parentheses) ---
        if paren_depth > 0 or join_buffer:
            join_buffer += " " + code.strip()
            join_raw += "\n" + raw
            paren_depth += code.count("(") - code.count(")")
            if paren_depth <= 0:
                # Parentheses closed — emit joined line
                logical_lines.append(LogicalLine(
                    text=join_buffer.strip(),
                    start_line=join_start_line,
                    end_line=line_num,
                    indent=_count_indent(lines[join_start_line - 1]),
                    raw=join_raw,
                ))
                join_buffer = ""
                join_raw = ""
                paren_depth = 0
            elif line_num - join_start_line > 10:
                # Safety: don't join more than 10 lines
                warnings.append(ParseWarning(
                    line_number=join_start_line,
                    category="multiline",
                    raw_line=join_raw[:200],
                    message=f"Multiline construct exceeds 10 lines (started at line {join_start_line}). Partial parse.",
                ))
                logical_lines.append(LogicalLine(
                    text=join_buffer.strip(),
                    start_line=join_start_line,
                    end_line=line_num,
                    indent=_count_indent(lines[join_start_line - 1]),
                    raw=join_raw,
                ))
                join_buffer = ""
                join_raw = ""
                paren_depth = 0
            continue

        # Check if this line starts a multiline construct
        open_parens = code.count("(") - code.count(")")
        if open_parens > 0:
            join_buffer = code.strip()
            join_start_line = line_num
            join_raw = raw
            paren_depth = open_parens
            continue

        # --- Emit single logical line ---
        logical_lines.append(LogicalLine(
            text=code.strip(),
            start_line=line_num,
            end_line=line_num,
            indent=indent,
            raw=raw,
        ))

    # Flush any remaining join buffer
    if join_buffer:
        warnings.append(ParseWarning(
            line_number=join_start_line,
            category="multiline",
            raw_line=join_buffer[:200],
            message="Unclosed parentheses at end of file.",
        ))

    return logical_lines, warnings


def _strip_inline_comment(line: str) -> str:
    """Strip # comments that aren't inside strings."""
    in_string = False
    string_char = ""
    i = 0
    while i < len(line):
        ch = line[i]
        if in_string:
            if ch == "\\" and i + 1 < len(line):
                i += 2  # Skip escaped character
                continue
            if ch == string_char:
                in_string = False
        else:
            if ch in ('"', "'"):
                in_string = True
                string_char = ch
            elif ch == "#":
                return line[:i]
        i += 1
    return line


def _count_indent(line: str) -> int:
    """Count leading whitespace as indent level."""
    count = 0
    for ch in line:
        if ch == "\t":
            count += 1
        elif ch == " ":
            count += 1
        else:
            break
    return count


# --------------------------------------------------------------------------
# Pass 2: Structural extraction
# --------------------------------------------------------------------------

# Compiled patterns (used after preprocessing, so lines are clean)
RE_EXTENDS_CLASS = re.compile(r'^extends\s+(\w+)')
RE_EXTENDS_PATH = re.compile(r'^extends\s+"([^"]+)"')
RE_EXTENDS_PRELOAD = re.compile(r'^extends\s+preload\(\s*"([^"]+)"\s*\)')
RE_CLASS_NAME = re.compile(r'^class_name\s+(\w+)')
RE_INNER_CLASS = re.compile(r'^class\s+(\w+)(?:\s+extends\s+(\w+))?\s*:')
RE_SIGNAL = re.compile(r'^signal\s+(\w+)(?:\(([^)]*)\))?')
RE_PRELOAD = re.compile(r'preload\(\s*"([^"]+)"\s*\)')
RE_LOAD = re.compile(r'(?<!\w)load\(\s*"([^"]+)"\s*\)')

# Function: static? func name(params) -> ReturnType:
# After multiline joining, this is always on one logical line
RE_FUNC = re.compile(
    r'^(?P<static>static\s+)?'
    r'func\s+'
    r'(?P<name>\w+)'
    r'\s*\((?P<params>[^)]*)\)'
    r'(?:\s*->\s*(?P<ret>[^:]+?))?'
    r'\s*:'
)

# Variable: [@decorator] var/const name [: Type] [= value]
RE_VAR = re.compile(
    r'^(?P<deco>@\w+\s+)?'
    r'(?P<kind>var|const)\s+'
    r'(?P<name>\w+)'
    r'(?:\s*:\s*(?P<type>[^=]+?))?'
    r'(?:\s*=\s*(?P<value>.+))?$'
)

# Type annotation parsing (handles Array[Type], Dictionary[K, V], etc.)
RE_TYPE_SIMPLE = re.compile(r'^(\w+)(?:\[([^\]]+)\])?$')


def _parse_type_annotation(raw: str) -> str:
    """
    Parse a type annotation string, returning the base type.
    'Array[Entity]' -> 'Array'
    'Node3D' -> 'Node3D'
    'Dictionary[String, int]' -> 'Dictionary'
    For Gate 1, we need the base type to check against forbidden types.
    """
    raw = raw.strip()
    m = RE_TYPE_SIMPLE.match(raw)
    if m:
        return m.group(1)
    # If we can't parse it, return as-is
    return raw


def _parse_return_type(raw: Optional[str]) -> Optional[str]:
    """Parse a return type annotation from a function signature."""
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    return _parse_type_annotation(raw)


def _parse_param_types(params_str: str) -> List[str]:
    """Extract parameter type annotations from a parameter list string."""
    if not params_str.strip():
        return []

    types = []
    # Split by comma, handling potential nested generics
    depth = 0
    current = ""
    for ch in params_str:
        if ch in ("(", "["):
            depth += 1
            current += ch
        elif ch in (")", "]"):
            depth -= 1
            current += ch
        elif ch == "," and depth == 0:
            types.append(_extract_param_type(current.strip()))
            current = ""
        else:
            current += ch

    if current.strip():
        types.append(_extract_param_type(current.strip()))

    return types


def _extract_param_type(param: str) -> str:
    """Extract type from a single parameter declaration like 'name: Type = default'."""
    # Remove default value
    if "=" in param:
        param = param[:param.index("=")].strip()

    # Extract type after colon
    if ":" in param:
        type_part = param.split(":", 1)[1].strip()
        return _parse_type_annotation(type_part)

    return ""  # No type annotation


def _extract(
    logical_lines: List[LogicalLine],
    result: GDFileAnalysis,
) -> None:
    """
    Pass 2: Extract structural information from preprocessed logical lines.
    Tracks scope via indentation to handle inner classes.
    """
    # Scope tracking
    current_scope = "top"
    scope_indent = 0  # Indent level of current inner class

    for ll in logical_lines:
        text = ll.text
        line_num = ll.start_line

        # --- Scope tracking for inner classes ---
        if current_scope != "top" and ll.indent <= scope_indent:
            current_scope = "top"
            scope_indent = 0

        # --- Inner class ---
        m = RE_INNER_CLASS.match(text)
        if m:
            cls_name = m.group(1)
            cls_extends = m.group(2)
            result.inner_classes.append(GDInnerClass(
                name=cls_name,
                extends=cls_extends,
                line_number=line_num,
                indent_level=ll.indent,
            ))
            current_scope = f"inner:{cls_name}"
            scope_indent = ll.indent
            continue

        # --- extends (top-level only) ---
        if current_scope == "top":
            m = RE_EXTENDS_PRELOAD.match(text)
            if m:
                result.extends_path = m.group(1)
                result.imports.append(GDImport("extends", m.group(1), line_num, ll.raw))
                continue

            m = RE_EXTENDS_PATH.match(text)
            if m:
                result.extends_path = m.group(1)
                result.imports.append(GDImport("extends", m.group(1), line_num, ll.raw))
                continue

            m = RE_EXTENDS_CLASS.match(text)
            if m:
                result.extends = m.group(1)
                continue

        # --- class_name ---
        m = RE_CLASS_NAME.match(text)
        if m:
            result.class_name = m.group(1)
            continue

        # --- signal ---
        m = RE_SIGNAL.match(text)
        if m:
            sig_name = m.group(1)
            sig_params = []
            if m.group(2):
                sig_params = [p.strip().split(":")[0].strip() for p in m.group(2).split(",")]
            result.signals.append(GDSignal(sig_name, line_num, sig_params))
            continue

        # --- func ---
        m = RE_FUNC.match(text)
        if m:
            name = m.group("name")
            is_static = m.group("static") is not None
            return_type = _parse_return_type(m.group("ret"))
            param_types = _parse_param_types(m.group("params"))

            has_warning = False
            # Check for complex return types we might mismatch
            raw_ret = m.group("ret")
            if raw_ret and ("[" in raw_ret or "," in raw_ret):
                # Complex generic — flag for review but still extract base type
                result.warnings.append(ParseWarning(
                    line_number=line_num,
                    category="complex_type",
                    raw_line=ll.raw[:200] if isinstance(ll.raw, str) else str(ll.raw)[:200],
                    message=f"Complex return type '{raw_ret.strip()}' — base type '{return_type}' extracted, verify manually.",
                ))
                has_warning = True

            result.functions.append(GDFunction(
                name=name,
                is_public=not name.startswith("_"),
                return_type=return_type,
                param_types=param_types,
                line_number=line_num,
                raw_line=ll.raw[:200] if isinstance(ll.raw, str) else str(ll.raw)[:200],
                is_static=is_static,
                scope=current_scope,
                has_parse_warning=has_warning,
            ))
            continue

        # --- var/const ---
        m = RE_VAR.match(text)
        if m:
            deco = (m.group("deco") or "").strip()
            kind = m.group("kind")
            if deco:
                kind = f"{deco} {kind}"
            name = m.group("name")
            type_hint = m.group("type")
            if type_hint:
                type_hint = type_hint.strip()
            value = m.group("value") or ""

            value_path = None
            # Check for preload/load in value
            pm = RE_PRELOAD.search(value)
            lm = RE_LOAD.search(value)
            if pm:
                value_path = pm.group(1)
                result.imports.append(GDImport("preload", value_path, line_num, ll.raw))
            elif lm:
                value_path = lm.group(1)
                result.imports.append(GDImport("load", value_path, line_num, ll.raw))

            result.variables.append(GDVariable(
                name=name, kind=kind, type_hint=type_hint,
                value_path=value_path, line_number=line_num,
            ))
            continue

        # --- Catch preload/load in any other context ---
        for pm in RE_PRELOAD.finditer(text):
            # Avoid duplicates from var/const parsing
            path = pm.group(1)
            if not any(imp.path == path and imp.line_number == line_num for imp in result.imports):
                result.imports.append(GDImport("preload", path, line_num, ll.raw))

        for lm in RE_LOAD.finditer(text):
            path = lm.group(1)
            if not any(imp.path == path and imp.line_number == line_num for imp in result.imports):
                result.imports.append(GDImport("load", path, line_num, ll.raw))


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def analyze_file(file_path: str) -> GDFileAnalysis:
    """
    Analyze a single GDScript file.

    Returns GDFileAnalysis with extracted structure and any parse warnings.
    Warnings indicate constructs the analyzer couldn't fully parse —
    Gate 1 should flag these for manual review.
    """
    result = GDFileAnalysis(file_path=file_path)
    path = Path(file_path)

    if not path.exists():
        result.errors.append(f"File not found: {file_path}")
        return result

    if path.suffix != ".gd":
        result.errors.append(f"Not a GDScript file: {file_path}")
        return result

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw_lines = f.readlines()
    except UnicodeDecodeError as e:
        result.errors.append(f"Encoding error: {e}")
        return result

    # Pass 1: Preprocess
    logical_lines, preprocess_warnings = _preprocess(raw_lines)
    result.warnings.extend(preprocess_warnings)

    # Pass 2: Extract
    _extract(logical_lines, result)

    logger.debug(
        "analyzer",
        f"Analyzed {file_path}: {len(result.functions)} functions, "
        f"{len(result.imports)} imports, {len(result.warnings)} warnings"
    )

    return result


def analyze_directory(dir_path: str, extensions: Set[str] = {".gd"}) -> List[GDFileAnalysis]:
    """Analyze all GDScript files in a directory recursively."""
    results = []
    root = Path(dir_path)
    if not root.exists():
        logger.warn("analyzer", f"Directory not found: {dir_path}")
        return results

    for gd_file in sorted(root.rglob("*")):
        if gd_file.suffix in extensions and gd_file.is_file():
            results.append(analyze_file(str(gd_file)))

    logger.info("analyzer", f"Analyzed {len(results)} files in {dir_path}")
    return results
