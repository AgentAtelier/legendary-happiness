from .pattern_library import PatternLibrary


class PatternExpander:
    """
    Expands gameplay patterns into entity definitions.
    """

    def __init__(self):

        self.library = PatternLibrary()

    def expand(self, plan):

        entities = plan.get("entities", [])

        expanded = []

        for entity in entities:
            pattern = self.library.get(entity["name"])

            if pattern:
                merged = {"name": entity["name"], "components": pattern["components"]}

                expanded.append(merged)

            else:
                expanded.append(entity)

        plan["entities"] = expanded

        return plan
