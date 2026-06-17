"""Balance report feature."""

from .base_feature import PreviewFeature
from devforge.simulation.preview.balance_report import BalanceReport


class ReportFeature(PreviewFeature):
    name = "report"

    def __init__(self):

        self.report = BalanceReport()

    # ---------------------------------------------------------

    def run(self, controller, **kwargs):

        metrics = controller.metrics()

        critique = controller.run_feature("critic")

        suggestions = controller.run_feature("suggestions")

        graph = controller.system_graph()

        return self.report.generate(
            metrics,
            critique,
            suggestions,
            graph,
        )
