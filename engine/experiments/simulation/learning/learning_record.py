from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class LearningRecord:

    prompt: str

    architecture: Dict[str, Any]

    operations: list

    success: bool

    metadata: Dict[str, Any]