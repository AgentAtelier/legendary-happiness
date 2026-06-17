"""LLM-backed plan generator for simple goal -> plan flow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from devforge.core.execution_plan import ExecutionPlan
from devforge.infrastructure.llm.router import LLMRouter
from devforge.reasoning.ai.planning.plan_cache import PlanCache
from devforge.reasoning.ai.planning.prompt_builder import PromptBuilder


def extract_json(text: str) -> str:
    """Extract the first balanced JSON object from text."""
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in LLM response")

    brace_count = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            brace_count += 1
        elif text[i] == "}":
            brace_count -= 1

        if brace_count == 0:
            return text[start : i + 1]

    raise ValueError("Unbalanced JSON braces in LLM response")


class PlanGenerator:
    def __init__(self, repo_root: Path | str | None = None):
        self.repo_root = Path(repo_root) if repo_root is not None else Path(".")
        self.router = LLMRouter()
        self.cache = PlanCache(self.repo_root)
        self.prompt_builder = PromptBuilder(self.repo_root / "game")

    def generate(self, goal: str) -> ExecutionPlan:
        cached = self.cache.get(goal)
        if isinstance(cached, ExecutionPlan):
            return cached
        if isinstance(cached, dict):
            return ExecutionPlan.model_validate(cached)

        prompt = self.prompt_builder.build_plan_prompt(goal)
        response = self.router.chat([{"role": "user", "content": prompt}])

        plan_json = json.loads(extract_json(response))
        if isinstance(plan_json, dict) and "steps" in plan_json:
            plan_dict: dict[str, Any] = {
                "spec_name": plan_json.get("spec_name", goal),
                "spec_version": plan_json.get("spec_version", "0.1.0"),
                "planner_model": plan_json.get("planner_model", "local_llama"),
                "steps": plan_json.get("steps", []),
            }
        else:
            plan_dict = {
                "spec_name": goal,
                "spec_version": "0.1.0",
                "planner_model": "local_llama",
                "steps": [plan_json],
            }

        plan = ExecutionPlan.model_validate(plan_dict)
        self.cache.set(goal, plan)
        return plan
