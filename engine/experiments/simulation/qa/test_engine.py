from devforge.qa.gameplay_simulator import GameplaySimulator


class TestEngine:
    def __init__(self):

        self.sim = GameplaySimulator()

    def run_tests(self, scene):

        results = []

        results += self.sim.simulate_player_input(scene)

        results += self.sim.simulate_combat(scene)

        return results
