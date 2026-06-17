from dataclasses import dataclass
from .base import PlanStep


@dataclass
class AttachComponentStep(PlanStep):
    entity: str
    component: str

    def __init__(self, entity: str, component: str):
        super().__init__(step_type="attach_component")
        self.entity = entity
        self.component = component


@dataclass
class CreateComponentStep(PlanStep):
    component_name: str

    def __init__(self, component_name: str):
        super().__init__(step_type="create_component")
        self.component_name = component_name