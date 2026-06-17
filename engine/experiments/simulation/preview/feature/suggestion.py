"""Design suggestion feature."""

from .base_feature import PreviewFeature
from devforge.simulation.preview.design_suggestion import DesignSuggestionEngine


class SuggestionFeature(PreviewFeature):

    name = "suggestions"

    def __init__(self):

        self.engine = DesignSuggestionEngine()

    # ---------------------------------------------------------

    def run(self, controller, **kwargs):

        metrics = controller.metrics()

        critique = controller.run_feature("critic")

        graph = controller.system_graph()

        memory = None

        return self.engine.suggest(
            metrics,
            critique,
            graph,
            memory,
        )