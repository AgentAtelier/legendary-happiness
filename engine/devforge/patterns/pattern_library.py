import json
from pathlib import Path


class PatternLibrary:
    """
    Loads gameplay patterns from disk.
    """

    def __init__(self, directory="devforge/patterns"):

        self.directory = Path(directory)
        self.patterns = {}

        self.load()

    def load(self):

        for file in self.directory.glob("*.json"):

            data = json.loads(file.read_text())

            self.patterns[data["name"]] = data

    def get(self, name):

        return self.patterns.get(name)