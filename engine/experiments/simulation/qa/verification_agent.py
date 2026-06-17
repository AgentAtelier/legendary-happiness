class VerificationAgent:

    def verify(self, scene_tree):

        results = []

        if not scene_tree:
            results.append(
                {
                    "status": "error",
                    "reason": "scene empty"
                }
            )

        return results