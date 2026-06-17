import json
from pathlib import Path
from typing import List

from devforge.learning.learning_record import LearningRecord


class LearningStore:
    def __init__(self, path="devforge_learning.json"):

        self.path = Path(path)

        if not self.path.exists():
            self.path.write_text("[]")

    # ─────────────────────────────

    def load(self) -> List[dict]:

        return json.loads(self.path.read_text())

    # ─────────────────────────────

    def save(self, record: LearningRecord):

        data = self.load()

        data.append(record.__dict__)

        self.path.write_text(json.dumps(data, indent=2))
