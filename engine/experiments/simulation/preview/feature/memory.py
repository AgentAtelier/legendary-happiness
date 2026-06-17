"""Design memory feature."""

from .base_feature import PreviewFeature
from devforge.simulation.preview.design_memory import DesignMemory


class MemoryFeature(PreviewFeature):

    name = "memory"

    def __init__(self):

        self.memory = DesignMemory()

    # ---------------------------------------------------------

    def run(self, controller, **kwargs):

        systems = controller.systems()

        metrics = controller.metrics()

        critique = controller.run_feature("critic")

        self.memory.store(
            systems,
            metrics,
            critique,
        )

        return {
            "stored_records": len(self.memory.records)
        }

    # ---------------------------------------------------------

    def query(self, metric):

        return self.memory.best_designs(metric)