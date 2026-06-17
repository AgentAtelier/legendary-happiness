from __future__ import annotations

from typing import Dict, List


class OperationCostModel:
    """
    Assigns risk/cost values to operations.

    Used to discourage dangerous structural modifications.
    """

    def __init__(self):

        self.costs: Dict[str, int] = {
            "add_entity": 2,
            "attach_script": 3,
            "create_file": 3,
            "modify_script": 6,
            "set_property": 4,
            "connect_signal": 4,
            "rename_node": 5,
            "remove_node": 8,
            "delete_scene": 10,
        }

    # ---------------------------------------------------------
    # Cost evaluation
    # ---------------------------------------------------------

    def cost(self, operation: Dict) -> int:

        op_type = operation.get("type", "")

        return self.costs.get(op_type, 5)

    # ---------------------------------------------------------
    # Plan scoring
    # ---------------------------------------------------------

    def score_plan(
        self,
        operations: List[Dict],
    ) -> int:

        total = 0

        for op in operations:
            total += self.cost(op)

        return total

    # ---------------------------------------------------------
    # Plan filtering
    # ---------------------------------------------------------

    def filter_dangerous(
        self,
        operations: List[Dict],
        threshold: int = 15,
    ) -> List[Dict]:

        safe: List[Dict] = []

        for op in operations:

            if self.cost(op) > threshold:
                continue

            safe.append(op)

        return safe