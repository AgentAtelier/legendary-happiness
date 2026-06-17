"""Scenario exploration feature."""

from .base_feature import PreviewFeature
from devforge.simulation.preview.scenario_explorer import ScenarioExplorer


class ExplorerFeature(PreviewFeature):
    name = "explorer"

    def __init__(self):

        self.engine = None

    # ---------------------------------------------------------

    def run(self, controller, **kwargs):

        if self.engine is None:
            self.engine = ScenarioExplorer(controller)

        ranges = kwargs.get(
            "ranges",
            {"weather": {"rain_variation": (0.05, 0.6)}},
        )

        runs = kwargs.get("runs", 50)

        return self.engine.explore(
            ranges,
            runs,
        )
