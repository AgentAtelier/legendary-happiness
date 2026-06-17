class PreviewNode:

    def __init__(self, name: str, node_type: str):
        self.name = name
        self.node_type = node_type

        self.children = []
        self.parent = None

        self.properties = {}
        self.script = None

    def add_child(self, node):

        node.parent = self
        self.children.append(node)

    def remove_child(self, name):

        for c in list(self.children):
            if c.name == name:
                self.children.remove(c)
                return

        raise RuntimeError(f"Child not found: {name}")

    def set_property(self, key, value):

        self.properties[key] = value

    def attach_script(self, script_path):

        self.script = script_path