"""Script Extractor — lifts GDScript code out of prompts deterministically.

REVIEW (Issue 3, cheap half): There is no path from prompt text to file
content. The planner's schema is ``{name, description}`` per system and
``_generate_system_script()`` stubs every system with an empty
``extends Node``. When the user pastes real GDScript into a prompt, it is
currently ignored.

This module runs *before* the planner. It:

  1. Detects fenced code blocks (``` ... ```) and recognizable GDScript
     fragments (lines matching ``extends \\w+`` or ``func \\w+(``) even
     when un-fenced.
  2. Maps each fragment to a script file path using either:
       - a preceding "Create Foo.gd" / "name it Foo.gd" mention, or
       - the ``class_name X`` declared inside the fragment, or
       - the file name embedded in a ``# path: foo.gd`` header.
  3. Returns ``(files, scrubbed_prompt)`` where ``files`` is a list of
     ``{"path": str, "content": str}`` ready to drop into the plan, and
     ``scrubbed_prompt`` is the prompt with extracted code removed so the
     planner does not plan duplicate systems for code it is about to
     emit as-is.

This is intentionally deterministic — no LLM call, no grammar change —
so it can never be the slow path of the pipeline.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from devforge.infrastructure.logger import logger


@dataclass
class ExtractedFile:
    path: str
    content: str


# ── Detection patterns ─────────────────────────────────────────

# Fenced code block: ```lang?\n...\n```
_FENCED_RE = re.compile(
    r"```(?:gdscript|gd|GDScript|GD)?\s*\n(.*?)```",
    re.DOTALL,
)

# Recognizable GDScript inside prose: lines starting with extends / func /
# class_name / @export / signal / var (with type), up to a blank-line
# break. Anchored to start-of-line; we collect the smallest contiguous
# block that contains at least one GDScript signature.
_GDSCRIPT_LINE_RE = re.compile(
    r"^(?:extends\s+\w+|class_name\s+\w+|func\s+\w+\s*\(|@export"
    r"(?:\s*\([^)]*\))?\s+var\s+\w+|signal\s+\w+|#\s*path:\s*\S+)",
)
# Filename hint near a fragment: "Create Foo.gd" / "name it Foo.gd" / "in Bar.gd"
_FILENAME_HINT_RE = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*\.gd)\b"
)
# Explicit "path: foo.gd" comment header inside a fragment
_PATH_HEADER_RE = re.compile(r"^\s*#\s*path:\s*(\S+\.gd)\s*$", re.MULTILINE)
# class_name X declaration
_CLASS_NAME_RE = re.compile(r"^\s*class_name\s+(\w+)\s*$", re.MULTILINE)


def extract(prompt: str) -> Tuple[List[ExtractedFile], str]:
    """Extract GDScript files from a prompt.

    Returns ``(files, scrubbed_prompt)``. ``files`` is empty when no
    recognizable GDScript is found. ``scrubbed_prompt`` has all
    extracted code removed and is what should be handed to the planner.
    """
    if not prompt or "```" not in prompt and not _looks_like_gdscript(prompt):
        return [], prompt

    files: List[ExtractedFile] = []
    scrubbed = prompt

    def _add_file(path: str, body: str) -> None:
        """Add an extracted fragment, merging on path collision.

        Two fragments can infer the same path (e.g. a script split at a
        blank line under one ``# path:`` header). Emitting both would
        make the executor's second script_create overwrite the first,
        silently losing content — merge instead.
        """
        for f in files:
            if f.path == path:
                if body.strip() and body.strip() not in f.content:
                    f.content = f"{f.content}\n\n{body}"
                return
        files.append(ExtractedFile(path=path, content=body))

    # 1. Fenced code blocks first (highest confidence)
    for match in _FENCED_RE.finditer(prompt):
        body = match.group(1).strip("\n")
        if not body or not _looks_like_gdscript(body):
            continue
        path = _infer_path(body, prompt, match.start())
        _add_file(path, body)
        # Remove the entire fence (with the optional lang tag)
        scrubbed = scrubbed.replace(match.group(0), "")

    # 2. Un-fenced GDScript fragments (collected greedily between signature
    #    lines and blank-line breaks)
    for body, span in _harvest_unfenced(scrubbed):
        if not body:
            continue
        path = _infer_path(body, prompt, None)
        _add_file(path, body)
        scrubbed = scrubbed.replace(body, "")

    # Tidy up whitespace left by removals
    scrubbed = re.sub(r"\n{3,}", "\n\n", scrubbed).strip()

    if files:
        logger.info(
            "script_extractor",
            f"Extracted {len(files)} script file(s) from prompt",
            paths=[f.path for f in files],
        )

    return files, scrubbed


# ── Helpers ────────────────────────────────────────────────────

def _looks_like_gdscript(text: str) -> bool:
    """Cheap heuristic: does the text contain at least one GDScript signature line?"""
    for line in text.splitlines():
        if _GDSCRIPT_LINE_RE.match(line):
            return True
    return False


def _harvest_unfenced(text: str) -> List[Tuple[str, Tuple[int, int]]]:
    """Find un-fenced GDScript fragments in prose.

    A fragment is a run of consecutive non-blank lines whose first line
    matches a GDScript signature.  Returns (body, span) pairs.
    """
    out: List[Tuple[str, Tuple[int, int]]] = []
    lines = text.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        if _GDSCRIPT_LINE_RE.match(lines[i]):
            start = i
            j = i
            buf: List[str] = []
            # collect until blank line or end
            while j < len(lines) and lines[j].strip():
                buf.append(lines[j])
                j += 1
            body = "".join(buf).rstrip()
            if body:
                out.append((body, (start, j)))
            i = j
        else:
            i += 1
    return out


def _infer_path(body: str, full_prompt: str, fence_pos: Optional[int]) -> str:
    """Pick a script path for a body. Order of preference:
    1. ``# path: foo.gd`` header inside the body (sanitized)
    2. ``class_name X`` → ``scripts/X.gd``
    3. Closest preceding ``Foo.gd`` mention in the prompt
    4. ``scripts/extracted_<hash>.gd`` fallback (content-based, deterministic)

    All paths are confined to ``scripts/`` — path traversal (``..``)
    and absolute paths are rejected.
    """
    # 1. Explicit path header — sanitize before use
    m = _PATH_HEADER_RE.search(body)
    if m:
        raw = m.group(1).lstrip("/")
        path = _sanitize_path(raw)
        if path:
            return path

    # 2. class_name — always safe (single identifier)
    m = _CLASS_NAME_RE.search(body)
    if m:
        return f"scripts/{m.group(1)}.gd"

    # 3. Closest preceding filename hint — sanitize
    if fence_pos is not None:
        prefix = full_prompt[:fence_pos]
    else:
        prefix = full_prompt
    hints = list(_FILENAME_HINT_RE.finditer(prefix))
    if hints:
        raw = hints[-1].group(1)
        path = _sanitize_path(raw)
        if path:
            return path

    # 4. Fallback — deterministic content hash, not Python's salted hash()
    digest = hashlib.sha1(body.encode("utf-8", errors="replace")).hexdigest()[:8]
    return f"scripts/extracted_{digest}.gd"


def _sanitize_path(raw: str) -> Optional[str]:
    """Sanitize a user-supplied or LLM-visible path.

    Rejects path traversal (``..``) and absolute paths.  Confines
    the result to ``scripts/``.  Returns None if the path is unsafe.
    """
    raw = raw.strip()
    if not raw:
        return None
    # Normalize and reject traversal
    if ".." in raw or raw.startswith("/") or raw.startswith("\\"):
        logger.warn("script_extractor", f"Rejected unsafe path: {raw!r}")
        return None
    # Strip any leading directory components — confine to scripts/
    basename = raw.split("/")[-1].split("\\")[-1]
    if not basename:
        return None
    if not basename.endswith(".gd"):
        basename += ".gd"
    return f"scripts/{basename}"


__all__ = ["ExtractedFile", "extract"]
