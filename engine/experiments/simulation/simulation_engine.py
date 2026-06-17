from devforge.simulation.world_state import WorldState


class SimulationEngine:
    def __init__(self):

        self.systems = []

        self.world = WorldState()

    # ─────────────────────────────────

    def add_system(self, system):

        self.systems.append(system)

    # ─────────────────────────────────

    def step(self, dt):

        for system in self.systems:
            system.update(self.world, dt)

        self.world.advance_time(dt)

    # ─────────────────────────────────

    def run(self, steps=100, dt=1.0):

        for _ in range(steps):
            self.step(dt)

        return self.world
