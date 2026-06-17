"""Updates the system graph based on successfully executed operations."""

from __future__ import annotations

from devforge.infrastructure.logger import logger
from devforge.knowledge.system_graph.system_graph import EdgeType, NodeType, SystemGraph


class GraphUpdater:
    def __init__(self, graph: SystemGraph):
        self.graph = graph

    def apply_operation(self, op: dict) -> None:
        op_type = op.get("type", "")

        try:
            if op_type == "add_node":
                self._handle_add_node(op)
            elif op_type == "attach_script":
                self._handle_attach_script(op)
            elif op_type == "remove_node":
                self._handle_remove_node(op)
        except Exception as exc:
            logger.warn("graph_updater", f"Failed to apply op to graph: {exc}", op=op)

    def _handle_add_node(self, op: dict) -> None:
        name = op.get("name", "")
        node_type = op.get("node_type", "Node3D")

        if not name:
            return

        node_id = name.lower().replace(" ", "_")

        if not self.graph.has_node(node_id):
            self.graph.add_node(node_id, name, NodeType.ENTITY, node_type=node_type)

    def _handle_attach_script(self, op: dict) -> None:
        node_path = op.get("node", "")
        script_path = op.get("script", "")

        if not node_path or not script_path:
            return

        node_name = node_path.split("/")[-1]
        node_id = node_name.lower().replace(" ", "_")
        script_id = f"script_{script_path.replace('/', '_')}"

        if not self.graph.has_node(script_id):
            self.graph.add_node(script_id, script_path, NodeType.SCRIPT)

        if self.graph.has_node(node_id):
            self.graph.add_edge(node_id, script_id, EdgeType.USES)

    def _handle_remove_node(self, op: dict) -> None:
        node_path = op.get("node", "")
        if not node_path:
            return

        node_name = node_path.split("/")[-1]
        node_id = node_name.lower().replace(" ", "_")
        self.graph.remove_node(node_id)
