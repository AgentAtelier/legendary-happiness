"""Runtime configuration for DevForge."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class RuntimeConfig:
    debug: bool = False
    max_repair_attempts: int = 3
    max_plan_retries: int = 3
    max_plan_steps: int = 100
    max_files_per_plan: int = 50

    # Phase 2: Token budget for context window (32K VRAM-limited)
    context_token_budget: int = 24000

    # Phase 6: Planner mode — "arch" (systems/entities/connections → compiler)
    # vs "ops" (direct operation generation).  A/B-tested before making ops
    # the default.
    planner_mode: str = "arch"

    # LLM settings
    llm_backend: str = "llama"
    llama_endpoint: str = "http://localhost:9090"
    llama_temperature: float = 0.2
    llama_max_tokens: int = 4096
    llama_grammar_path: str = ""
    # Per-request LLM timeout. A 7K-token prefill plus 4K generation on
    # consumer GPUs (e.g. RX 6800) can legitimately exceed the old 120s.
    llm_timeout_s: int = 300

    # Prompt template for the llama backend ("gemma", "chatml", "raw")
    llm_prompt_template: str = "gemma"

    claude_model: str = "claude-sonnet-4-6"
    claude_max_tokens: int = 8192

    # Executor settings
    # S3: default to godot_ai_mcp — the plugin executor cannot execute
    # over MCP, and the MCP server _init() refuses to start with it.
    executor_backend: str = "godot_ai_mcp"
    godot_ai_mcp_url: str = "http://localhost:8000/mcp"

    # Property serialization hints (from one-time Godot round-trip)
    # Maps property name → serialization format ("vector", "color", "resource_path", etc.)
    property_serialization: dict = field(default_factory=dict)

    # Per-stage sampler profiles for tuned generation quality
    # Keys: "arch" (planning), "ops" (operation gen), "scripts" (GDScript),
    #       "decomp" (feature decomposition)
    sampler_profiles: dict = field(default_factory=lambda: {
        "arch": {"temperature": 0.2, "top_p": 0.9, "top_k": 40},
        "ops": {"temperature": 0.2, "top_p": 0.9, "top_k": 40},
        "scripts": {"temperature": 0.4, "top_p": 0.95, "top_k": 64},
        "decomp": {"temperature": 0.3, "top_p": 0.9, "top_k": 40},
    })

    # Paths
    game_root: str = "./dev-forge"

    # ── Validation (M1) ────────────────────────────────────────

    VALID_LLM_BACKENDS = {"llama", "claude", "mock"}
    VALID_EXECUTOR_BACKENDS = {"godot_ai_mcp", "devforge_plugin"}
    VALID_SAMPLER_STAGES = {"arch", "ops", "scripts", "decomp"}
    VALID_PROMPT_TEMPLATES = {"gemma", "chatml", "raw"}
    VALID_PLANNER_MODES = {"arch", "ops", "layout", "building", "scatter", "ssp", "room", "wfc", "voronoi"}

    def validate(self) -> list[str]:
        """Return a list of configuration errors (empty = valid).

        Call ``get_config()`` and then ``validate()`` at startup to
        catch typos and impossible values before they become 2 a.m.
        mysteries deep inside the pipeline.
        """
        errors: list[str] = []

        if self.llm_backend not in self.VALID_LLM_BACKENDS:
            errors.append(
                f"llm_backend='{self.llm_backend}' is not one of "
                f"{sorted(self.VALID_LLM_BACKENDS)}"
            )

        if self.executor_backend not in self.VALID_EXECUTOR_BACKENDS:
            errors.append(
                f"executor_backend='{self.executor_backend}' is not one of "
                f"{sorted(self.VALID_EXECUTOR_BACKENDS)}"
            )

        if self.max_plan_retries < 1:
            errors.append(
                f"max_plan_retries={self.max_plan_retries} must be >= 1"
            )

        if self.max_repair_attempts < 0:
            errors.append(
                f"max_repair_attempts={self.max_repair_attempts} must be >= 0"
            )

        if self.max_plan_steps < 1:
            errors.append(
                f"max_plan_steps={self.max_plan_steps} must be >= 1"
            )

        if self.max_files_per_plan < 1:
            errors.append(
                f"max_files_per_plan={self.max_files_per_plan} must be >= 1"
            )

        if self.context_token_budget < 1:
            errors.append(
                f"context_token_budget={self.context_token_budget} must be >= 1"
            )

        if self.llama_max_tokens < 1:
            errors.append(
                f"llama_max_tokens={self.llama_max_tokens} must be >= 1"
            )

        if self.claude_max_tokens < 1:
            errors.append(
                f"claude_max_tokens={self.claude_max_tokens} must be >= 1"
            )

        if self.llama_temperature < 0:
            errors.append(
                f"llama_temperature={self.llama_temperature} must be >= 0"
            )

        if self.llm_timeout_s < 1:
            errors.append(
                f"llm_timeout_s={self.llm_timeout_s} must be >= 1"
            )

        if self.llm_prompt_template not in self.VALID_PROMPT_TEMPLATES:
            errors.append(
                f"llm_prompt_template='{self.llm_prompt_template}' is not one of "
                f"{sorted(self.VALID_PROMPT_TEMPLATES)}"
            )

        if self.planner_mode not in self.VALID_PLANNER_MODES:
            errors.append(
                f"planner_mode='{self.planner_mode}' is not one of "
                f"{sorted(self.VALID_PLANNER_MODES)}"
            )

        # Validate sampler profiles
        unknown_stages = set(self.sampler_profiles.keys()) - self.VALID_SAMPLER_STAGES
        if unknown_stages:
            errors.append(
                f"sampler_profiles contains unknown stages: "
                f"{sorted(unknown_stages)}. Valid: {sorted(self.VALID_SAMPLER_STAGES)}"
            )

        for stage, profile in self.sampler_profiles.items():
            if not isinstance(profile, dict):
                errors.append(
                    f"sampler_profiles['{stage}'] is not a dict"
                )
                continue
            temp = profile.get("temperature")
            if temp is not None and (not isinstance(temp, (int, float)) or temp < 0):
                errors.append(
                    f"sampler_profiles['{stage}'].temperature={temp} must be >= 0"
                )

        return errors

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        return cls(
            debug=os.getenv("DEVFORGE_DEBUG", "0") == "1",
            max_repair_attempts=int(os.getenv("DEVFORGE_MAX_REPAIR_ATTEMPTS", "3")),
            max_plan_retries=int(os.getenv("DEVFORGE_MAX_PLAN_RETRIES", "3")),
            max_plan_steps=int(os.getenv("DEVFORGE_MAX_PLAN_STEPS", "100")),
            max_files_per_plan=int(os.getenv("DEVFORGE_MAX_FILES_PER_PLAN", "50")),
            context_token_budget=int(os.getenv("DEVFORGE_CONTEXT_TOKEN_BUDGET", "24000")),
            llm_backend=os.getenv("DEVFORGE_LLM_BACKEND", "llama"),
            llama_endpoint=os.getenv("DEVFORGE_LLAMA_ENDPOINT", "http://localhost:9090"),
            llama_temperature=float(os.getenv("DEVFORGE_LLAMA_TEMPERATURE", "0.2")),
            llama_max_tokens=int(os.getenv("DEVFORGE_LLAMA_MAX_TOKENS", "4096")),
            llama_grammar_path=os.getenv("DEVFORGE_GRAMMAR_PATH", ""),  # empty = auto-generate
            llm_timeout_s=int(os.getenv("DEVFORGE_LLM_TIMEOUT", "300")),
            llm_prompt_template=os.getenv("DEVFORGE_PROMPT_TEMPLATE", "gemma"),
            planner_mode=os.getenv("DEVFORGE_PLANNER", "arch"),
            claude_model=os.getenv("DEVFORGE_CLAUDE_MODEL", "claude-sonnet-4-6"),
            claude_max_tokens=int(os.getenv("DEVFORGE_CLAUDE_MAX_TOKENS", "8192")),
            executor_backend=os.getenv("DEVFORGE_EXECUTOR_BACKEND", "godot_ai_mcp"),
            godot_ai_mcp_url=os.getenv("DEVFORGE_GODOT_AI_MCP_URL", "http://localhost:8000/mcp"),
            game_root=os.getenv("DEVFORGE_GAME_ROOT", "./dev-forge"),
        )


# Tokens the full prompt needs beyond the assembled context: the static
# planner template (~450 tokens), the user request, Gemma chat-template
# tokens, and retry-suffix headroom. Conservative on purpose.
PROMPT_OVERHEAD_TOKENS = 1024

# Below this many context tokens the planner can't see enough of the
# scene/architecture to plan well — flag it instead of failing silently.
MIN_USEFUL_CONTEXT_TOKENS = 2048


def effective_context_budget(
    n_ctx: int,
    llama_max_tokens: int,
    configured_budget: int,
    overhead_tokens: int = PROMPT_OVERHEAD_TOKENS,
) -> int:
    """Largest context budget that actually fits the server window.

    llama.cpp holds prompt AND generation in one window of ``n_ctx``
    tokens; a context budget configured beyond
    ``n_ctx - max_tokens - overhead`` makes the server silently drop the
    oldest prompt tokens — which is the instruction prefix, the worst
    possible thing to lose.
    """
    available = n_ctx - llama_max_tokens - overhead_tokens
    return min(configured_budget, max(available, 0))


# ── Model alias → prompt-template auto-detection ────────────────
# Maps model alias substrings (lowercased) to prompt templates.
# Used by apply_server_limits to auto-set DEVFORGE_PROMPT_TEMPLATE
# when the user hasn't explicitly configured one via env or the
# `stack model` dotfiles command.

_MODEL_TO_TEMPLATE: list[tuple[str, str]] = [
    ("qwen", "chatml"),
    ("yi", "chatml"),
    ("internlm", "chatml"),
    ("chatml", "chatml"),
    ("gemma", "gemma"),
]


def detect_prompt_template(model_alias: str) -> str | None:
    """Infer the prompt template from a llama.cpp model alias.

    Returns the template name ("gemma", "chatml", "raw") or None if
    the alias doesn't match any known model family.  Intentionally
    conservative — only returns results for families we're sure about.

    ``model_alias`` is the value reported by llama.cpp's /props
    endpoint (the ``--alias`` flag passed to llama-server).
    """
    alias_lower = model_alias.lower()
    for hint, template in _MODEL_TO_TEMPLATE:
        if hint in alias_lower:
            return template
    return None


# Singleton
_config: RuntimeConfig | None = None


def get_config() -> RuntimeConfig:
    global _config
    if _config is None:
        config = RuntimeConfig.from_env()
        # ── Validation (M1): catch typos at startup ──────────
        errs = config.validate()
        if errs:
            import sys
            print(
                "\n".join(f"[CONFIG ERROR] {e}" for e in errs),
                file=sys.stderr,
            )
            # Fail loudly (F7): a typo'd backend or impossible limit
            # must not run silently with surprise behavior.
            raise ValueError(
                "Invalid DevForge configuration: " + "; ".join(errs)
            )
        _config = config
    return _config


def set_config(config: RuntimeConfig) -> None:
    global _config
    _config = config
