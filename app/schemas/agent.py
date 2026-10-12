from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)


class FinishAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["answered", "needs_clarification"]

    answer: str = Field(min_length=1, max_length=4000)
    warnings: list[str] = Field(default_factory=list, max_length=8)

    # 引用成功工具调用的 request_id。
    evidence_ids: list[str] = Field(
        default_factory=list,
        max_length=6,
    )


class ToolEvidence(BaseModel):
    request_id: str
    tool: str
    arguments: dict
    data: dict


class ChatResponse(BaseModel):
    status: Literal["answered", "needs_clarification", "failed"]

    answer: str
    warnings: list[str] = Field(default_factory=list)
    evidence: list[ToolEvidence] = Field(default_factory=list)