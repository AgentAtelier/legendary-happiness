class Component:
    """
    Gameplay component attached to an entity.
    """

    def __init__(self, type: str, properties=None):

        self.type = type
        self.properties = properties or {}