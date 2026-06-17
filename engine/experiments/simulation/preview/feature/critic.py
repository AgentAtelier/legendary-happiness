"""Design critic feature."""

from .base_feature import PreviewFeature
from devforge.simulation.preview.design_critic import DesignCritic


class CriticFeature(PreviewFeature):

    name = "critic"

    def __init__(self):

        self.critic = DesignCritic()

    # ---------------------------------------------------------

    def run(self, controller, **kwargs):

        metrics = controller.metrics()

        events = controller.events()

        timeline = controller.timeline()

        graph = controller.system_graph()

        return self.critic.analyze(metrics, events, timeline, graph)