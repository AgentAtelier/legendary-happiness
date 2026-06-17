"""Context Assembler — builds the full context window for the LLM.

Phase 2: Token-budgeted, relevance-ranked context assembly for 32K window.
Combines: architecture graph, scene hierarchy, existing code (ranked by
relevance), prompt history, and recent session operations.

Replaces the old MAX_FILES / MAX_FILE_SIZE char-count approach with
a hard token budget allocated by section priority.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

from devforge.knowledge.system_graph.system_graph import SystemGraph
from devforge.infrastructure.logger import logger
from devforge.infrastructure.runtime_config import get_config


def _get_token_counter():
    """Lazy-load a token counter from the LLM client (if available).

    Returns a callable text → int | None, or None if unavailable.
    """
    try:
        from devforge.infrastructure.llm.router import LLMRouter

        llm = LLMRouter.get()
        backend = getattr(llm, "_backend", None)
        if backend and hasattr(backend, "tokenize"):
            return backend.tokenize
    except Exception:
        logger.warning("context_assembler", "token_counter unavailable")
        pass
    return None


class ContextAssembler:
    MAX_HISTORY = 5
    MAX_RECENT_OPERATIONS = 20

    # GDScript signature pattern — extracts declarations without tree-sitter
    # Matches: class_name, extends, func, signal, @export var, const, enum
    SIG_PATTERN = re.compile(
        r"^\s*("
        r"class_name\s+\w+"
        r"|extends\s+\w+"
        r"|func\s+\w+\s*\([^)]*\)(?:\s*->\s*\w+)?"
        r"|signal\s+\w+"
        r"|@export(?:\s*\([^)]*\))?\s*var\s+\w+"
        r"|const\s+\w+"
        r"|enum\s+\w+"
        r")",
        re.MULTILINE,
    )

    def __init__(
        self,
        game_root: Path | str,
        system_graph: SystemGraph,
        history: Optional[List[str]] = None,
    ):
        self.game_root = Path(game_root)
        self.system_graph = system_graph
        self.history: List[str] = history or []
        self._recent_operations: List[str] = []

        # Budget from runtime config
        budget = get_config().context_token_budget
        # Use len//4 as rough token estimate (conservative — overestimates slightly)
        self._arch_chars = int(budget * 0.15) * 4
        self._scene_chars = int(budget * 0.20) * 4
        self._code_chars = int(budget * 0.55) * 4
        self._hist_chars = int(budget * 0.10) * 4

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assemble(
        self,
        scene_tree: Dict,
        prompt: str,
        minimal: bool = False,
        signatures_only: bool = False,
    ) -> str:
        """Build the full context string for an LLM prompt.

        Sections are filled in priority order (architecture → scene →
        code → history) and each is capped at its token-budget allocation.

        If *minimal* is True, only architecture + scene are included
        (used for escalating retry when full context failed).

        If *signatures_only* is True, the code-context section is forced
        into signature-stub mode for every script, regardless of relevance
        score. This is the correct mode for the architecture planner:
        the planner's output schema (names, types, connections) cannot
        use full bodies, so paying the token cost for them is pure waste.
        At Forgeborn scale this saves 8–10K tokens per turn.
        """
        sections: List[str] = []

        sections.append(self._architecture_context())
        sections.append(self._scene_context(scene_tree))

        if not minimal:
            sections.append(self._code_context(prompt, signatures_only=signatures_only))
            sections.append(self._history_context())

        context = "\n\n".join(s for s in sections if s)

        # Use accurate token count if /tokenize is available
        token_count: int | None = None
        counter = _get_token_counter()
        if counter:
            token_count = counter(context)

        logger.info(
            "context_assembler",
            "Context assembled",
            chars=len(context),
            estimated_tokens=token_count if token_count is not None else len(context) // 4,
            method="tokenize" if token_count is not None else "heuristic",
        )
        return context

    def record_operation(self, operation) -> None:
        """Record an operation executed during the session.

        Absorbed from IncrementalContextBuilder — allows future prompts
        to know what was recently built.
        """
        try:
            text = str(operation)
        except Exception:
            text = repr(operation)

        self._recent_operations.append(text)
        if len(self._recent_operations) > self.MAX_RECENT_OPERATIONS:
            self._recent_operations.pop(0)

    # ------------------------------------------------------------------
    # Section builders — each returns a string, capped at its budget
    # ------------------------------------------------------------------

    def _architecture_context(self) -> str:
        lines = ["## Project Architecture"]
        try:
            ctx = self.system_graph.build_context()
            if len(ctx) > self._arch_chars:
                ctx = ctx[: self._arch_chars] + "\n... (architecture truncated)"
            lines.append(ctx)
        except Exception:
            lines.append("(no architecture data)")
        return "\n".join(lines)

    def _scene_context(self, scene_tree: Dict) -> str:
        lines = ["## Scene Hierarchy"]
        char_count = len(lines[0])

        def count_children(n: Dict) -> int:
            c = 0
            for ch in n.get("children", []):
                name = ch.get("name", "")
                ntype = ch.get("type", "Node")
                if name not in ("DevForgePanel", "PromptInput", "RunButton") and "HTTPRequest" not in ntype:
                    c += 1 + count_children(ch)
            return c

        def walk(node: Dict, depth: int = 0):
            nonlocal char_count
            name = node.get("name", "unknown")
            node_type = node.get("type", "Node")

            # Filter editor UI nodes
            if name in ("DevForgePanel", "PromptInput", "RunButton"):
                return
            if "HTTPRequest" in node_type:
                return

            indent = "  " * depth

            # Depth cap: summarize deep subtrees instead of walking them
            if depth >= 6:
                hidden = count_children(node)
                line = f"{indent}- {name} ({node_type})"
                if hidden > 0:
                    line += f" ... ({hidden} children)"
                lines.append(line)
                char_count += len(line)
                return

            line = f"{indent}- {name} ({node_type})"
            lines.append(line)
            char_count += len(line)

            for child in node.get("children", []):
                if char_count < self._scene_chars:
                    walk(child, depth + 1)

        walk(scene_tree)

        if char_count >= self._scene_chars:
            lines.append("... (scene truncated)")

        return "\n".join(lines)

    def _code_context(self, prompt: str, signatures_only: bool = False) -> str:
        """Include GDScript files ranked by relevance to the prompt.

        Highest-scoring files get full body inclusion.  Overflow / zero-score
        files get signature stubs only.

        If ``signatures_only`` is True, *every* file is rendered as
        signatures only — full bodies are never included regardless of
        score. Use this for prompts whose downstream consumer does not
        need file bodies (e.g. the architecture planner, whose output
        schema cannot reference code at all).
        """
        lines = ["## Existing Scripts"]
        scripts = list(self.game_root.rglob("*.gd"))
        if not scripts:
            lines.append("(none)")
            return "\n".join(lines)

        # Extract keywords from prompt (3+ char words, lowercase)
        keywords = {w.lower() for w in re.findall(r"[a-zA-Z_]{3,}", prompt)}

        # Score each file by relevance
        scored: list[tuple[int, Path, str]] = []
        for path in scripts:
            score = 0
            name_lower = path.stem.lower()
            for kw in keywords:
                if kw in name_lower:
                    score += 5  # filename match is strongest signal

            content = ""
            try:
                content = path.read_text(errors="ignore")
                head = content[:2000].lower()
                for kw in keywords:
                    score += head.count(kw)
            except Exception:
                logger.warning("context_assembler", f"failed to read script {path}: suppressed")
                pass

            # Prefer smaller files (fit more in budget)
            scored.append((score, path, content))

        scored.sort(key=lambda x: (-x[0], -x[1].stat().st_size if x[1].exists() else 0))

        full_count = 0
        chars_so_far = len(lines[0])
        for score, path, content in scored:
            rel = path.relative_to(self.game_root)

            # REVIEW (Issue 5): signatures-only mode short-circuits the
            # full-body branch for every file, eliminating the 8–10K
            # token cost the planner was paying for code it cannot use.
            if signatures_only:
                # Respect the code budget even in signatures-only mode.
                # Scripts are sorted by relevance, so once the budget is spent
                # the remaining (low-relevance) files are listed by name only.
                # Without this, a project with many scripts (e.g. 114 in the
                # godot_ai addon) blew the planner context to ~15K tokens and
                # DROWNED the request — and overflowed small-window models.
                if chars_so_far >= self._code_chars:
                    line = f"- {rel}"
                    lines.append(line)
                    chars_so_far += len(line) + 1
                    continue
                sigs = "\n".join(self.SIG_PATTERN.findall(content))
                if sigs:
                    chunk = f"\n### {rel} (signatures only)\n{sigs}"
                else:
                    chunk = f"\n### {rel}  [body elided]"
                lines.append(chunk)
                chars_so_far += len(chunk)
                continue

            if score == 0 or chars_so_far >= self._code_chars:
                # Overflow or zero-relevance: signatures only
                sigs = self.SIG_PATTERN.findall(content)
                if not sigs:
                    lines.append(f"- {rel}  [body elided]")
                else:
                    preview = ", ".join(s.strip() for s in sigs[:6])
                    lines.append(f"- {rel}  ({preview}...)")
                continue

            # Estimate cost before building the full chunk
            estimated = len(f"\n### {rel}\n") + len(content)
            if chars_so_far + estimated <= self._code_chars:
                chunk = f"\n### {rel}\n{content}"
                lines.append(chunk)
                chars_so_far += len(chunk)
                full_count += 1
            else:
                # Won't fit full body — fall back to signatures
                sigs = "\n".join(self.SIG_PATTERN.findall(content))
                if sigs:
                    chunk = f"\n### {rel} (signatures only)\n{sigs}"
                else:
                    chunk = f"\n### {rel}  [body elided — token budget]"
                lines.append(chunk)
                chars_so_far += len(chunk)

        if len(lines) == 1:
            lines.append("(none)")

        total = len(scored)
        if full_count < total:
            lines.insert(
                1,
                f"({full_count} of {total} scripts shown in full — token budget)",
            )

        return "\n".join(lines)

    def _history_context(self) -> str:
        lines = ["## Event History"]

        if self.history:
            lines.append("\n### Recent Prompts")
            for p in self.history[-self.MAX_HISTORY :]:
                lines.append(f"- {p}")

        if self._recent_operations:
            lines.append("\n### Recent Operations")
            for op in self._recent_operations:
                lines.append(f"- {op}")

        result = "\n".join(lines)
        if len(result) > self._hist_chars:
            result = result[: self._hist_chars] + "\n... (history truncated)"

        return result
