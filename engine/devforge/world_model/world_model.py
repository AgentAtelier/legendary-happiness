from .entity import Entity


class WorldModel:
    """
    Semantic model of the game world.
    """

    def __init__(self):

        self.entities = {}

    def create_entity(self, name):

        if name in self.entities:
            return self.entities[name]

        entity = Entity(name)

        self.entities[name] = entity

        return entity

    def get_entity(self, name):

        return self.entities.get(name)

    def all_entities(self):

        return list(self.entities.values())
