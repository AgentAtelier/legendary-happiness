from __future__ import annotations

from typing import Dict, Any, List


class PreviewController:
    """
    PreviewController for the simulation lab.

    IMPORTANT:
    The simulation subsystem is part of DevForge Year-3 architecture
    and is intentionally isolated so that the main DevForge server
    can run without the preview system being fully implemented.
    """

    def __init__(self):

        try:
            from .engine import PreviewEngine
            from .scenarios import ScenarioRunner
            from .experiments import ExperimentRunner
            from .system_graph_builder import SystemGraphBuilder
            from .adapter import PreviewAdapter

            from .feature_registry import FeatureRegistry

            from .feature.critic import CriticFeature
            from .feature.balancer import BalancerFeature
            from .feature.evolution import EvolutionFeature
            from .feature.memory import MemoryFeature
            from .feature.suggestion import SuggestionFeature
            from .feature.report import ReportFeature
            from .feature.explorer import ExplorerFeature
            from .graph_view import GraphViewFeature

        except Exception as exc:
            raise RuntimeError(
                "Simulation preview subsystem is not fully installed. "
                "This is expected during early DevForge development."
            ) from exc

        self.engine = PreviewEngine()

        self.scenario_runner = ScenarioRunner(self.engine)

        self.experiments = ExperimentRunner(self.engine)

        self.graph_builder = SystemGraphBuilder()

        self.adapter = PreviewAdapter()

        self.features = FeatureRegistry()

        self._register_features()

        self.features.register(SuggestionFeature())
        self.features.register(ReportFeature())
        self.features.register(ExplorerFeature())
        self.features.register(GraphViewFeature())

    # ---------------------------------------------------------

    def _register_features(self):

        from .feature.critic import CriticFeature
        from .feature.balancer import BalancerFeature
        from .feature.evolution import EvolutionFeature
        from .feature.memory import MemoryFeature

        self.features.register(CriticFeature())
        self.features.register(BalancerFeature())
        self.features.register(EvolutionFeature())
        self.features.register(MemoryFeature())

    # ---------------------------------------------------------

    def run_feature(self, name, **kwargs):

        return self.features.run(name, self, **kwargs)

    # ---------------------------------------------------------

    def reset(self):

        self.engine.reset()

    # ---------------------------------------------------------

    def step(self, dt: float = 1.0):

        self.engine.step(dt)

    # ---------------------------------------------------------

    def run(self, steps: int = 100, dt: float = 1.0):

        self.engine.run(steps, dt)

    # ---------------------------------------------------------

    def add_system(self, system):

        self.engine.add_system(system)

    # ---------------------------------------------------------

    def add_generated_system(self, data: Dict[str, Any]):

        system = self.adapter.create_system(data)

        self.engine.add_system(system)

    # ---------------------------------------------------------

    def set_parameter(self, system_name: str, parameter: str, value):

        self.engine.set_parameter(system_name, parameter, value)

    # ---------------------------------------------------------

    def parameters(self):

        from .visualization import build_parameter_view

        params = self.engine.system_parameters()

        return build_parameter_view(params)

    # ---------------------------------------------------------

    def snapshot(self):

        from .visualization import build_world_snapshot

        return build_world_snapshot(self.engine.world)

    # ---------------------------------------------------------

    def timeline(self):

        from .visualization import build_environment_timeseries

        frames = self.engine.timeline_frames()

        return build_environment_timeseries(frames)

    # ---------------------------------------------------------

    def events(self):

        from .visualization import build_event_timeline

        frames = self.engine.timeline_frames()

        return build_event_timeline(frames)

    # ---------------------------------------------------------

    def metrics(self):

        return self.engine.metric_results()

    # ---------------------------------------------------------

    def system_graph(self):

        return self.graph_builder.build(self.engine)

    # ---------------------------------------------------------

    def run_scenario(self, scenario):

        return self.scenario_runner.run_scenario(scenario)

    # ---------------------------------------------------------

    def run_experiment(self, scenarios):

        return self.experiments.compare(scenarios)
