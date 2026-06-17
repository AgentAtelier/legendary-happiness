import random

from devforge.simulation.system import SimulationSystem


class DisasterSystem(SimulationSystem):

    def update(self, world_state, dt):

        if random.random() < 0.01:

            event = random.choice(
                [
                    "earthquake",
                    "flood",
                    "volcano",
                ]
            )

            world_state.systems[event] = {
                "time": world_state.time
            }