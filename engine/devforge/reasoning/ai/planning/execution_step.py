from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ExecutionStep(BaseModel):
    step_id: str = Field(default_factory=lambda: str(uuid4()))
    operation_type: str
    target_file: str
    payload: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
