"""Quest Graph — build and analyze quest dependency graphs.

Deterministic core (tier 0): graph algorithms, no LLM calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class QuestNode:
    """A single quest in the dependency graph."""

    id: str
    name: str = ""
    prerequisites: list[str] = field(default_factory=list)
    required_items: list[str] = field(default_factory=list)
    grants_items: list[str] = field(default_factory=list)
    required_flags: list[str] = field(default_factory=list)
    sets_flags: list[str] = field(default_factory=list)


@dataclass
class GraphIssue:
    """A reachability or soft-lock issue found in the quest graph."""

    issue_type: str  # "unreachable" | "cycle" | "item_deadlock" | "flag_deadlock"
    severity: str  # "CRITICAL" | "WARNING"
    quests: list[str]  # involved quest IDs
    message: str  # plain-language explanation of the problem

    def to_dict(self) -> dict:
        return {
            "issue_type": self.issue_type,
            "severity": self.severity,
            "quests": self.quests,
            "message": self.message,
        }


class QuestGraph:
    """Directed graph of quest dependencies with reachability analysis."""

    def __init__(self, quests: list[QuestNode]):
        self._quests: dict[str, QuestNode] = {q.id: q for q in quests}

        # Adjacency: quest → list of quests it unlocks
        self._unlocks: dict[str, list[str]] = {qid: [] for qid in self._quests}

        # Reverse: quest → list of quests that must be done first
        self._required_by: dict[str, list[str]] = {qid: [] for qid in self._quests}

        for q in quests:
            for prereq in q.prerequisites:
                if prereq in self._unlocks:
                    self._unlocks[prereq].append(q.id)
                    self._required_by[q.id].append(prereq)

    def all_quests(self) -> list[str]:
        return list(self._quests.keys())

    def get(self, quest_id: str) -> QuestNode | None:
        return self._quests.get(quest_id)

    def start_nodes(self) -> list[str]:
        """Quests with no prerequisites — the entry points."""
        return [qid for qid, q in self._quests.items() if not q.prerequisites]

    def _compute_reachable(self) -> set[str]:
        """Compute the set of quests reachable from start nodes via BFS."""
        reachable: set[str] = set()
        stack = list(self.start_nodes())

        while stack:
            qid = stack.pop()
            if qid in reachable:
                continue
            if qid not in self._quests:
                continue
            reachable.add(qid)
            stack.extend(self._unlocks.get(qid, []))

        return reachable

    def find_unreachable(self) -> list[GraphIssue]:
        """Find quests that can't be reached from any start node."""
        reachable: set[str] = set()
        stack = list(self.start_nodes())

        while stack:
            qid = stack.pop()
            if qid in reachable:
                continue
            if qid not in self._quests:
                continue
            reachable.add(qid)
            stack.extend(self._unlocks.get(qid, []))

        unreachable = set(self._quests) - reachable
        if not unreachable:
            return []

        return [
            GraphIssue(
                issue_type="unreachable",
                severity="CRITICAL",
                quests=sorted(unreachable),
                message=(
                    f"{len(unreachable)} quest(s) are unreachable from any "
                    f"starting quest: {', '.join(sorted(unreachable))}. "
                    f"Check prerequisites — these quests may have missing or "
                    f"circular dependencies."
                ),
            )
        ]

    def find_cycles(self) -> list[GraphIssue]:
        """Find prerequisite cycles (A requires B, B requires A)."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {qid: WHITE for qid in self._quests}
        cycles: list[list[str]] = []

        def _dfs(qid: str, path: list[str]) -> None:
            color[qid] = GRAY
            path.append(qid)
            for prereq in self._quests[qid].prerequisites:
                if prereq not in color:
                    continue
                if color[prereq] == GRAY:
                    # Found a cycle — extract the cycle portion
                    cycle_start = path.index(prereq)
                    cycles.append(path[cycle_start:] + [prereq])
                elif color[prereq] == WHITE:
                    _dfs(prereq, path)
            path.pop()
            color[qid] = BLACK

        for qid in self._quests:
            if color[qid] == WHITE:
                _dfs(qid, [])

        if not cycles:
            return []

        # Deduplicate cycles (same cycle, different starting points)
        unique_cycles: list[list[str]] = []
        seen: set[frozenset] = set()
        for cycle in cycles:
            frozen = frozenset(cycle)
            if frozen not in seen:
                seen.add(frozen)
                unique_cycles.append(cycle)

        issues: list[GraphIssue] = []
        for cycle in unique_cycles:
            cycle_str = " → ".join(cycle)
            issues.append(
                GraphIssue(
                    issue_type="cycle",
                    severity="CRITICAL",
                    quests=cycle,
                    message=(
                        f"Prerequisite cycle detected: {cycle_str}. "
                        f"This creates a soft-lock — no quest in the cycle "
                        f"can ever be started."
                    ),
                )
            )
        return issues

    def find_item_deadlocks(self) -> list[GraphIssue]:
        """Find item deadlocks: quest requires an item that only it grants."""
        # Compute reachable quests once for all checks
        reachable = self._compute_reachable()
        issues: list[GraphIssue] = []

        for qid, q in self._quests.items():
            for item in q.required_items:
                if item in q.grants_items:
                    issues.append(
                        GraphIssue(
                            issue_type="item_deadlock",
                            severity="WARNING",
                            quests=[qid],
                            message=(
                                f"Quest '{q.name or qid}' requires item "
                                f"'{item}' but also grants it — the player "
                                f"can never satisfy this requirement on "
                                f"the first playthrough."
                            ),
                        )
                    )
                    continue

                # Check if the item can come from any reachable source
                can_obtain = False
                for other_id, other in self._quests.items():
                    if other_id == qid:
                        continue
                    if item in other.grants_items and other_id in reachable:
                        can_obtain = True
                        break

                if not can_obtain:
                    issues.append(
                        GraphIssue(
                            issue_type="item_deadlock",
                            severity="CRITICAL",
                            quests=[qid],
                            message=(
                                f"Quest '{q.name or qid}' requires item "
                                f"'{item}' but no reachable quest grants it. "
                                f"Either add a quest that grants '{item}' "
                                f"or remove it from the requirements."
                            ),
                        )
                    )

        return issues

    def find_flag_deadlocks(self) -> list[GraphIssue]:
        """Find flag deadlocks: quest requires a flag that no quest sets."""
        all_set_flags: set[str] = set()
        for q in self._quests.values():
            all_set_flags.update(q.sets_flags)

        issues: list[GraphIssue] = []
        for qid, q in self._quests.items():
            for flag in q.required_flags:
                if flag not in all_set_flags:
                    issues.append(
                        GraphIssue(
                            issue_type="flag_deadlock",
                            severity="CRITICAL",
                            quests=[qid],
                            message=(
                                f"Quest '{q.name or qid}' requires flag "
                                f"'{flag}' but no quest sets it. "
                                f"Either add a quest that sets '{flag}' "
                                f"or remove it from the requirements."
                            ),
                        )
                    )

        return issues

    def validate(self) -> dict:
        """Run all checks and return aggregated results."""
        issues = self.find_unreachable() + self.find_cycles() + self.find_item_deadlocks() + self.find_flag_deadlocks()

        critical = sum(1 for i in issues if i.severity == "CRITICAL")
        warning = sum(1 for i in issues if i.severity == "WARNING")

        return {
            "total_quests": len(self._quests),
            "start_nodes": len(self.start_nodes()),
            "issue_count": len(issues),
            "critical": critical,
            "warning": warning,
            "issues": [i.to_dict() for i in issues],
        }
