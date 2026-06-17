from ..component_library import ComponentLibrary


class EntityCompiler:

    def __init__(self):

        self.library = ComponentLibrary()

    def compile(self, world):

        operations = []

        for entity in world.all_entities():

            entity_ops = self._compile_entity(entity)

            operations.extend(entity_ops)

        return operations

    def _compile_entity(self, entity):

        ops = []

        root_path = "/root"

        ops.append({
            "type": "add_node",
            "parent": root_path,
            "name": entity.name,
            "node_type": "CharacterBody3D"
        })

        entity_path = f"/root/{entity.name}"

        for component in entity.components:

            comp = self.library.get(component.type)

            if not comp:
                continue

            for op in comp["operations"]:

                ops.append(self._resolve(op, entity_path))

        return ops

    def _resolve(self, op, entity_path):

        resolved = {}

        for k, v in op.items():

            if isinstance(v, str):
                resolved[k] = v.replace("{entity}", entity_path)
            else:
                resolved[k] = v

        return resolved