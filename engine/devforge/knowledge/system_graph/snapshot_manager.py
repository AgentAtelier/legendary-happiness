from __future__ import annotations

import copy
import time
from typing import Dict, List

from devforge.knowledge.system_graph.system_graph import SystemGraph


class ArchitectureSnapshotManager:
    """
    Manages snapshots of SystemGraph for rollback and debugging.
    """

    MAX_SNAPSHOTS = 20

    def __init__(self):

        self.snapshots: List[Dict] = []

    # ---------------------------------------------------------
    # Snapshot creation
    # ---------------------------------------------------------

    def create_snapshot(
        self,
        graph: SystemGraph,
        label: str = "",
    ):

        snapshot = {
            "timestamp": time.time(),
            "label": label,
            "nodes": copy.deepcopy(graph.nodes),
            "edges": copy.deepcopy(graph.edges),
        }

        self.snapshots.append(snapshot)

        if len(self.snapshots) > self.MAX_SNAPSHOTS:
            self.snapshots.pop(0)

    # ---------------------------------------------------------
    # Restore
    # ---------------------------------------------------------

    def restore_last(
        self,
        graph: SystemGraph,
    ):

        if not self.snapshots:
            return

        snapshot = self.snapshots[-1]

        graph.nodes = copy.deepcopy(snapshot["nodes"])
        graph.edges = copy.deepcopy(snapshot["edges"])

    # ---------------------------------------------------------
    # Restore by label
    # ---------------------------------------------------------

    def restore_by_label(
        self,
        graph: SystemGraph,
        label: str,
    ):

        for snap in reversed(self.snapshots):

            if snap["label"] == label:

                graph.nodes = copy.deepcopy(snap["nodes"])
                graph.edges = copy.deepcopy(snap["edges"])

                return

    # ---------------------------------------------------------
    # Snapshot history
    # ---------------------------------------------------------

    def list_snapshots(self):

        result = []

        for snap in self.snapshots:

            result.append(
                {
                    "label": snap["label"],
                    "timestamp": snap["timestamp"],
                }
            )

        return result