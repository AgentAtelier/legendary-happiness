from .world_model import WorldModel
from .component import Component
from devforge.reasoning.architectural_reasoner import ArchitecturalReasoner
from devforge.patterns.pattern_expander import PatternExpander


class EntityBuilder:

    def __init__(self):

        self.world = WorldModel()
        self.reasoner = ArchitecturalReasoner()
        self.patterns = PatternExpander()

    def build(self, plan):

        # Expand gameplay patterns
        plan = self.patterns.expand(plan)

        entities = plan.get("entities", [])

        for e in entities:

            entity = self.world.create_entity(e["name"])

            for comp in e.get("components", []):

                entity.add_component(
                    Component(comp["type"], comp.get("properties"))
                )

        # Architecture reasoning
        self.reasoner.apply(self.world)

        return self.world