"""Mechanic evolution feature."""

from .base_feature import PreviewFeature
from devforge.simulation.preview.mechanic_evolution import MechanicEvolution


class EvolutionFeature(PreviewFeature):

    name = "evolution"

    def __init__(self):

        self.engine = None

    # ---------------------------------------------------------

    def run(self, controller, **kwargs):

        if self.engine is None:
            self.engine = MechanicEvolution(controller)

        systems = kwargs.get("systems", [])

        return self.engine.evolve(systems)