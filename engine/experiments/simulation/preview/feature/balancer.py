"""Auto balancing feature."""

from .base_feature import PreviewFeature
from devforge.simulation.preview.auto_balancer import AutoBalancer


class BalancerFeature(PreviewFeature):
    name = "balancer"

    def __init__(self):

        self.balancer = None

    # ---------------------------------------------------------

    def run(self, controller, **kwargs):

        if self.balancer is None:
            self.balancer = AutoBalancer(controller)

        targets = kwargs.get("targets", {})

        return self.balancer.balance(targets)
