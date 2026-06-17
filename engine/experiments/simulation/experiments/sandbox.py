class Sandbox:

    def __init__(self):

        self.experiments = []

    def run(self, idea):

        result = {
            "idea": idea,
            "status": "tested"
        }

        self.experiments.append(result)

        return result