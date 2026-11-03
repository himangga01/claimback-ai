"""Common agent formats (design 4-1, M2a task 3)."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class AgentTask(BaseModel):
    """Work order for one agent run."""

    case_id: str = Field(..., description="사건 ID")
    agent: str = Field(..., description="담당 이름")
    inputs: Dict[str, Any] = Field(
        default_factory=dict, description="CaseState 구역의 ID·값"
    )
    constraints: Dict[str, Any] = Field(
        default_factory=dict, description="예산, 언어, 재시도 횟수"
    )


class AuditRecord(BaseModel):
    """One auditable agent execution (design 4-1 + step/ex_id)."""

    step: str = Field(default="", description="단계 key (reading 등)")
    ex_id: Optional[str] = Field(default=None, description="증거 ID (판독)")
    model_id: Optional[str] = Field(default=None, description="모델 ID (규칙이면 None)")
    prompt_version: Optional[str] = Field(default=None, description="프롬프트 버전")
    input_hashes: List[str] = Field(default_factory=list, description="입력 해시")
    latency_ms: int = Field(default=0, description="소요 시간(ms)")
    tokens_in: int = Field(default=0, description="입력 토큰")
    tokens_out: int = Field(default=0, description="출력 토큰")
    cost_usd: float = Field(default=0.0, description="비용(USD)")


class AgentResult(BaseModel):
    """One agent run result."""

    agent: str = Field(..., description="담당 이름")
    status: Literal["ok", "hold", "fail"] = Field(..., description="결과 상태")
    outputs: Dict[str, Any] = Field(default_factory=dict, description="담당별 출력")
    warnings: List[str] = Field(default_factory=list, description="경고")
    audit: AuditRecord = Field(..., description="감사 기록")


class AgentSchemaError(ValueError):
    """Model output failed schema validation twice (evidence/case HOLD)."""
