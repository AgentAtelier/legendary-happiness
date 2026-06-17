from devforge.knowledge.knowledge_graph import KnowledgeGraph


class KnowledgeBuilder:

    def build(self, system_graph):

        graph = KnowledgeGraph()

        for entity in system_graph.entities:

            graph.add_node(entity)

        for system in system_graph.systems:

            graph.add_node(system)

        for entity in system_graph.entities.values():

            for system in entity.systems:

                graph.add_edge(
                    entity.name,
                    "uses",
                    system,
                )

        return graph