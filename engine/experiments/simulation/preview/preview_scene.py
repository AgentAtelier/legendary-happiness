from .preview_node import PreviewNode


class PreviewScene:

    def __init__(self):
        self.root = PreviewNode("root", "Node")

    def find(self, path):

        parts = [p for p in path.split("/") if p]

        if not parts:
            return None

        node = self.root

        for part in parts[1:]:

            found = None

            for child in node.children:
                if child.name == part:
                    found = child
                    break

            if not found:
                return None

            node = found

        return node

    def add_node(self, parent_path, name, node_type):

        parent = self.find(parent_path)

        if parent is None:
            raise RuntimeError(f"Parent not found: {parent_path}")

        node = PreviewNode(name, node_type)

        parent.add_child(node)

        return node

    def remove_node(self, path):

        parts = [p for p in path.split("/") if p]

        if len(parts) < 2:
            raise RuntimeError("Cannot remove root")

        parent_path = "/".join(parts[:-1])
        node_name = parts[-1]

        parent = self.find(parent_path)

        if parent is None:
            raise RuntimeError("Parent not found")

        parent.remove_child(node_name)

    def attach_script(self, node_path, script_path):

        node = self.find(node_path)

        if node is None:
            raise RuntimeError("Node not found")

        node.attach_script(script_path)

    def set_property(self, node_path, key, value):

        node = self.find(node_path)

        if node is None:
            raise RuntimeError("Node not found")

        node.set_property(key, value)

    def dump(self):

        result = []

        def walk(node, depth=0):

            result.append("  " * depth + f"{node.node_type}:{node.name}")

            for c in node.children:
                walk(c, depth + 1)

        walk(self.root)

        return "\n".join(result)