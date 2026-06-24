"""Metric — a self-describing number. The reporting layer reads unit and
higher_is_better to format correctly; it never guesses.

This is the root fix for the ×100 / "broke is better" class of bugs.
"""

from __future__ import annotations

from typing import Literal

Unit = Literal["ratio", "percent", "count", "ms", "tok_s", "bool", "score"]


class Metric:
    """A typed, self-describing measurement value.

    Attributes:
        value: The raw number (or bool for unit="bool").
        unit: The kind of measurement — determines display formatting.
        higher_is_better: Whether larger values are better (coloring, stars).
        label: Human-readable short name for the metric.
    """

    __slots__ = ("value", "unit", "higher_is_better", "label")

    def __init__(
        self,
        value: float | int | bool,
        unit: Unit,
        higher_is_better: bool,
        label: str,
    ) -> None:
        self.value = value
        self.unit = unit
        self.higher_is_better = higher_is_better
        self.label = label

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "unit": self.unit,
            "higher_is_better": self.higher_is_better,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Metric:
        return cls(d["value"], d["unit"], d["higher_is_better"], d["label"])

    # ── convenience constructors ──────────────────────────────────

    @classmethod
    def ratio(cls, value: float, label: str, higher_is_better: bool = True) -> Metric:
        return cls(value, "ratio", higher_is_better, label)

    @classmethod
    def percent(cls, value: float, label: str, higher_is_better: bool = True) -> Metric:
        return cls(value, "percent", higher_is_better, label)

    @classmethod
    def count(cls, value: int, label: str, higher_is_better: bool = True) -> Metric:
        return cls(value, "count", higher_is_better, label)

    @classmethod
    def milliseconds(cls, value: int, label: str, higher_is_better: bool = False) -> Metric:
        return cls(value, "ms", higher_is_better, label)

    @classmethod
    def boolean(cls, value: bool, label: str) -> Metric:
        return cls(value, "bool", True, label)

    @classmethod
    def score(cls, value: int, label: str = "score") -> Metric:
        return cls(value, "score", True, label)
