class Entity:
    """
    High-level gameplay entity representation.
    """

    def __init__(self, name: str):

        self.name = name
        self.components = []

    def add_component(self, component):

        self.components.append(component)

    def has_component(self, component_type):

        for c in self.components:
            if c.type == component_type:
                return True

        return False