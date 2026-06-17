from .entity_compiler import EntityCompiler


class WorldCompiler:
    """
    Converts the entire world model into DevForge operations.
    """

    def __init__(self):

        self.entity_compiler = EntityCompiler()

    def compile(self, world):

        operations = []

        operations.extend(
            self.entity_compiler.compile(world)
        )

        return operations