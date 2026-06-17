class PreviewValidator:
    """
    Validates a simulated scene to ensure architectural correctness.
    """

    REQUIRED_CHILDREN = {
        "CharacterBody3D": ["CollisionShape3D"],
        "RigidBody3D": ["CollisionShape3D"],
    }

    INVALID_CHILDREN = {
        "Camera3D": ["CollisionShape3D"],
    }

    def validate(self, scene):

        errors = []

        self._validate_node(scene.root, errors)

        return errors

    def _validate_node(self, node, errors):

        children_types = [c.node_type for c in node.children]

        # Required components
        if node.node_type in self.REQUIRED_CHILDREN:
            required = self.REQUIRED_CHILDREN[node.node_type]

            for r in required:
                if r not in children_types:
                    errors.append(f"{node.node_type}:{node.name} missing required child {r}")

        # Invalid combinations
        if node.node_type in self.INVALID_CHILDREN:
            invalid = self.INVALID_CHILDREN[node.node_type]

            for c in children_types:
                if c in invalid:
                    errors.append(f"{node.node_type}:{node.name} cannot contain {c}")

        # Duplicate child names
        names = set()
        for child in node.children:
            if child.name in names:
                errors.append(f"Duplicate node name: {child.name}")
            names.add(child.name)

        # Recursive validation
        for child in node.children:
            self._validate_node(child, errors)
