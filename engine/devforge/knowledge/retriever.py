class KnowledgeRetriever:
    def search(self, graph, keyword):

        results = []

        for node in graph.nodes:
            if keyword.lower() in node.lower():
                results.append(node)

        return results
