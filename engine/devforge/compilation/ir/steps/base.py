from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class PlanStep:
    """
    Base class for all reasoning plan steps.

    Plan steps represent architectural intent.
    They are later compiled into deterministic operations.
    """

    step_type: str

    # ---------------------------------------------------------
    # Validation
    # ---------------------------------------------------------

    def validate(self) -> None:
        """
        Override in subclasses if needed.
        """
        pass

    # ---------------------------------------------------------
    # Compilation
    # ---------------------------------------------------------

    def compile(self) -> list[Dict[str, Any]]:
        """
        Convert this step into execution operations.

        Subclasses must implement this.
        """
        raise NotImplementedError(f"{self.__class__.__name__} must implement compile()")

    # ---------------------------------------------------------
    # Serialization
    # ---------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:

        data = {"type": self.step_type}

        for k, v in self.__dict__.items():
            if k == "step_type":
                continue
            data[k] = v

        return data
