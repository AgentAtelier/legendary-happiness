import random

from devforge.simulation.system import SimulationSystem


class WeatherSystem(SimulationSystem):

    def update(self, world_state, dt):

        world_state.environment["rain"] += random.uniform(-0.1, 0.1)
        world_state.environment["wind"] += random.uniform(-0.05, 0.05)

        world_state.environment["rain"] = max(
            0, min(1, world_state.environment["rain"])
        )

        world_state.environment["wind"] = max(
            0, min(1, world_state.environment["wind"])
        )