from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class BoundaryDecision(BaseModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    confidence: float = Field(ge=0.0, le=1.0)
    source_quote: str | None = None

    @model_validator(mode="after")
    def end_after_start(self) -> "BoundaryDecision":
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self


class CriticVerdict(BaseModel):
    passed: bool


class AgentAction(BaseModel):
    """LLM-planned next action for the browser agent."""

    done: bool = Field(
        description="True if the task is already complete based on current page state."
    )
    action: str = Field(
        default="none",
        description="Action type: click | type | scroll | press_key | navigate | none",
    )
    selector: str = Field(
        default="",
        description="CSS selector, role/name, or text content to target.",
    )
    value: str = Field(
        default="",
        description="Text to type, key to press, or URL to navigate to.",
    )
    reasoning: str = Field(
        default="",
        description="One-sentence explanation of why this action advances the task.",
    )
