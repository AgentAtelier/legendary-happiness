from __future__ import annotations

import json
from typing import Callable

from devforge.compilation.ir.plan import DevForgePlan
from devforge.compilation.ir.steps.scene_steps import (
    CreateEntityStep,
    CreateScriptStep,
    AttachScriptStep,
    SetPropertyStep,
)

from devforge.compilation.ir.steps.component_steps import (
    CreateComponentStep,
    AttachComponentStep,
)

from devforge.reasoning.prompts.planner_prompt import PlannerPromptTemplate
from devforge.reasoning.ai.planning.feature_decomposer import FeatureDecomposer


class PlanningOrchestrator:
    """
    Planning stage of DevForge.

    Converts prompts into architecture features
    and generates plans for each feature.
    """

    def __init__(self):

        self.decomposer = FeatureDecomposer()

    # ---------------------------------------------------------

    def plan(
        self,
        *,
        prompt: str,
        context: str,
        llm: Callable[[str], str],
    ) -> DevForgePlan:

        features = self.decomposer.decompose(prompt, llm)

        all_steps = []

        for feature in features:

            llm_prompt = PlannerPromptTemplate.build(feature, context)

            response = llm(llm_prompt)

            raw_steps = self._parse_json(response)

            steps = self._convert_steps(raw_steps)

            all_steps.extend(steps)

        return DevForgePlan(
            goal=prompt,
            steps=all_steps,
        )

    # ---------------------------------------------------------

    def _parse_json(self, response: str):

        if not response:
            return []

        try:

            data = json.loads(response)

            if isinstance(data, list):
                return data

        except Exception:
            pass

        return []

    # ---------------------------------------------------------

    def _convert_steps(self, raw_steps):

        steps = []

        for step in raw_steps:

            if not isinstance(step, dict):
                continue

            step_type = step.get("type")

            # ----------------------------
            # Scene Steps
            # ----------------------------

            if step_type == "create_entity":

                steps.append(
                    CreateEntityStep(
                        name=step.get("name", "Entity"),
                        node_type=step.get("node_type", "Node3D"),
                        parent=step.get("parent", "/root/Main"),
                    )
                )

            elif step_type == "create_script":

                path = step.get("path")

                if path:

                    steps.append(
                        CreateScriptStep(
                            path=path,
                            content=step.get("content", ""),
                        )
                    )

            elif step_type == "attach_script":

                node = step.get("node")
                script = step.get("script")

                if node and script:

                    steps.append(
                        AttachScriptStep(
                            node=node,
                            script=script,
                        )
                    )

            elif step_type == "set_property":

                node = step.get("node")
                prop = step.get("property")

                if node and prop:

                    steps.append(
                        SetPropertyStep(
                            node=node,
                            property=prop,
                            value=step.get("value"),
                        )
                    )

            # ----------------------------
            # Component Steps
            # ----------------------------

            elif step_type == "create_component":

                name = step.get("component")

                if name:

                    steps.append(
                        CreateComponentStep(
                            component_name=name
                        )
                    )

            elif step_type == "attach_component":

                entity = step.get("entity")
                component = step.get("component")

                if entity and component:

                    steps.append(
                        AttachComponentStep(
                            entity=entity,
                            component=component,
                        )
                    )

        return steps