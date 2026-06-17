from typing import Dict, List

from devforge.knowledge.scene.scene_graph import SceneGraph

SUPPORTED_OPERATIONS = {
    "add_node",
    "remove_node",
    "rename_node",
    "attach_script",
    "set_property",
    "connect_signal",
    "add_child_scene",
    "add_action_mapping",
}


class OperationValidator:
    def __init__(self, scene: SceneGraph):
        self.scene = scene

    # -----------------------------------------------------

    def validate(self, operations: List[Dict]) -> List[Dict]:
        """
        Validate a list of operations and return only safe ones.
        """

        valid = []

        for op in operations:
            op_type = op.get("type")

            if op_type not in SUPPORTED_OPERATIONS:
                continue

            method = getattr(self, f"_validate_{op_type}", None)

            if method and method(op):
                valid.append(op)

        return valid

    # -----------------------------------------------------

    def _validate_add_node(self, op: Dict) -> bool:

        parent = op.get("parent")
        node_type = op.get("node_type")

        if not parent or not node_type:
            return False

        if not self.scene.find_by_path(parent):
            return False

        return True

    # -----------------------------------------------------

    def _validate_remove_node(self, op: Dict) -> bool:

        node = op.get("node")

        if not node:
            return False

        if not self.scene.find_by_path(node):
            return False

        return True

    # -----------------------------------------------------

    def _validate_rename_node(self, op: Dict) -> bool:

        node = op.get("node")
        new_name = op.get("new_name")

        if not node or not new_name:
            return False

        if not self.scene.find_by_path(node):
            return False

        return True

    # -----------------------------------------------------

    def _validate_attach_script(self, op: Dict) -> bool:

        node = op.get("node")
        script = op.get("script")

        if not node or not script:
            return False

        if not self.scene.find_by_path(node):
            return False

        return True

    # -----------------------------------------------------

    def _validate_set_property(self, op: Dict) -> bool:

        node = op.get("node")
        prop = op.get("property")

        if not node or not prop:
            return False

        node_obj = self.scene.find_by_path(node)

        if not node_obj:
            return False

        return True

    # -----------------------------------------------------

    def _validate_connect_signal(self, op: Dict) -> bool:

        source = op.get("source")
        signal = op.get("signal")
        target = op.get("target")

        if not source or not signal or not target:
            return False

        src_node = self.scene.find_by_path(source)
        tgt_node = self.scene.find_by_path(target)

        if not src_node or not tgt_node:
            return False

        if signal not in src_node.signals:
            return False

        return True

    # -----------------------------------------------------

    def _validate_add_child_scene(self, op: Dict) -> bool:

        parent = op.get("parent")
        scene = op.get("scene")

        if not parent or not scene:
            return False

        if not self.scene.find_by_path(parent):
            return False

        return True
