import json
from pathlib import Path


class ComponentLibrary:
    """
    Loads gameplay components from disk.
    """

    def __init__(self, directory="devforge/components"):

        self.directory = Path(directory)
        self.components = {}

        self.load()

    def load(self):

        for file in self.directory.glob("*.json"):
            data = json.loads(file.read_text())

            self.components[data["name"]] = data

    def get(self, name):

        return self.components.get(name)
