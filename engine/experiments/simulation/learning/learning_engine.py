from devforge.learning.learning_store import LearningStore
from devforge.learning.learning_record import LearningRecord


class LearningEngine:
    def __init__(self):

        self.store = LearningStore()

    # ─────────────────────────────

    def learn(self, prompt, architecture, operations, success):

        record = LearningRecord(
            prompt=prompt,
            architecture=architecture,
            operations=operations,
            success=success,
            metadata={},
        )

        self.store.save(record)

    # ─────────────────────────────

    def retrieve(self, keyword):

        data = self.store.load()

        results = []

        for item in data:
            if keyword.lower() in item["prompt"].lower():
                results.append(item)

        return results
