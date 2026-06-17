from collections import defaultdict


class KnowledgeGraph:
    def __init__(self):

        self.nodes = set()

        self.edges = defaultdict(list)

    # ─────────────────────────────

    def add_node(self, name):

        self.nodes.add(name)

    # ─────────────────────────────

    def add_edge(self, source, relation, target):

        self.edges[source].append(
            {
                "relation": relation,
                "target": target,
            }
        )

    # ─────────────────────────────

    def neighbors(self, node):

        return self.edges.get(node, [])

    # ─────────────────────────────

    def describe(self):

        return {
            "nodes": list(self.nodes),
            "edges": dict(self.edges),
        }
