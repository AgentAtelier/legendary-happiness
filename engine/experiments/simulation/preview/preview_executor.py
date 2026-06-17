from .preview_world import PreviewWorld
from .preview_validator import PreviewValidator


class PreviewExecutor:
    """
    Executes operations inside a simulated world and validates the result.
    """

    def __init__(self):
        self.world = PreviewWorld()
        self.validator = PreviewValidator()

    def run(self, scene_name: str, operations):

        scene = self.world.apply_operations(scene_name, operations)

        errors = self.validator.validate(scene)

        if errors:
            raise RuntimeError("Preview validation failed:\n" + "\n".join(errors))

        return scene
