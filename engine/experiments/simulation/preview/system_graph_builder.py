"""Builds dependency graph from PreviewEngine systems."""

from __future__ import annotations

from typing import Any

from .system_graph import SystemGraph


class SystemGraphBuilder:
    def build(self, engine) -> dict:

        graph = SystemGraph()

        for system in engine.systems:
            inputs = getattr(system, "inputs", [])

            outputs = getattr(system, "outputs", [])

            graph.add_system(
                system.name,
                inputs,
                outputs,
            )

        return graph.export()
