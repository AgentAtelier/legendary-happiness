from .gameplay_rules import RULES
from devforge.world_model.component import Component


class ArchitecturalReasoner:
    """
    Infers missing gameplay components.
    """

    def apply(self, world):

        for entity in world.all_entities():

            self._apply_entity_rules(entity)

    def _apply_entity_rules(self, entity):

        # Entity type rules
        if entity.name in RULES:

            for comp in RULES[entity.name]:

                if not entity.has_component(comp):

                    entity.add_component(Component(comp))

        # Component dependency rules
        for component in list(entity.components):

            if component.type in RULES:

                for dep in RULES[component.type]:

                    if not entity.has_component(dep):

                        entity.add_component(Component(dep))