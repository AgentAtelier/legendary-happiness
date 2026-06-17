from __future__ import annotations

from devforge.reasoning.ai.context.builder import ContextBuilder


class PromptBuilder:
    def __init__(self, game_root):
        self.game_root = game_root
        self.context_builder = ContextBuilder(game_root)

    def build_plan_prompt(self, goal: str) -> str:
        context = self.context_builder.build(goal)
        return (
            "You are an expert Godot 4 game development AI.\n\n"
            "Generate an ExecutionPlan as JSON.\n\n"
            "## Project Context\n"
            f"{context}\n\n"
            "## Goal\n"
            f"{goal}\n\n"
            "Rules:\n"
            "1. Valid GDScript 4 only\n"
            f"2. Place files in {self.game_root}/\n"
            "3. Use snake_case files and PascalCase class_name\n"
            "4. Return only JSON with steps\n"
        )
