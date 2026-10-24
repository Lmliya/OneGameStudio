"""自进化领域模型。

所有对象都可用 Pydantic 序列化落盘，字段刻意保持扁平，便于人工审计。
安全边界通过 `ALLOWED_CHANGE_KEYS` / `PROTECTED_KEYS` 在模型层直接约束：
进化提案只能改提示词与检查清单，任何涉及工具权限、契约、模型的字段都会被拒绝。
"""

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, computed_field, model_validator

TalentVersionStatus = Literal["candidate", "active", "inactive", "rejected"]
LessonStatus = Literal["candidate", "verified", "rejected"]
ApprovalStatus = Literal["pending", "approved", "rejected"]
EvaluationStatus = Literal["pending", "passed", "failed"]
EvaluationEngine = Literal["mock", "live"]

# 进化允许修改的内容（仅内容层）
ALLOWED_CHANGE_KEYS: frozenset[str] = frozenset({"prompt", "checklist"})
# 明确禁止被进化触碰的系统安全边界
PROTECTED_KEYS: frozenset[str] = frozenset(
    {
        "allowed_tools",
        "tools",
        "shell",
        "output_schema",
        "schema",
        "model",
        "api_key",
        "llm_api_key",
        "budget",
        "budget_usd",
        "max_output_tokens",
        "gate",
        "quality_gate",
        "preview_csp",
        "sandbox",
        "file_system",
        "filesystem",
        "core",
        "engine",
    }
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:10]}"


def validate_changes(changes: dict) -> None:
    """拒绝任何触碰安全边界的变更键（提案与版本创建共用）。"""
    if not isinstance(changes, dict) or not changes:
        raise ValueError("proposed_changes 不能为空")
    keys = {str(key).lower() for key in changes}
    protected = keys & PROTECTED_KEYS
    if protected:
        raise ValueError(f"进化提案不得修改安全边界字段：{sorted(protected)}")
    unknown = keys - ALLOWED_CHANGE_KEYS
    if unknown:
        raise ValueError(f"进化提案只允许修改 {sorted(ALLOWED_CHANGE_KEYS)}，拒绝了 {sorted(unknown)}")


class TalentVersion(BaseModel):
    """某个 Talent 的一个不可变版本。

    版本文件一旦写入就不再覆盖；当前启用哪一版由 active.json 指针决定。
    `allowed_tools` / `output_schema` / `model` 是从基线复制的只读镜像，
    用于证明进化没有改动安全边界（启用时会与基线逐字段比对）。
    """

    talent_name: str
    version: int = Field(ge=1)
    parent_version: int | None = None
    prompt: str = Field(min_length=1)
    checklist: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    change_reason: str = ""
    evaluation_result: str | None = None
    status: TalentVersionStatus = "candidate"
    proposal_id: str | None = None

    # 只读镜像：不允许进化修改
    allowed_tools: list[str] = Field(default_factory=list)
    output_schema: str = ""
    model: str | None = None

    @computed_field
    @property
    def label(self) -> str:
        return f"{self.talent_name}@v{self.version}"

    @property
    def content(self) -> dict:
        """可被比较的内容部分（用于判断两版是否真的不同）。"""
        return {"prompt": self.prompt, "checklist": self.checklist}


class Lesson(BaseModel):
    """一条经验。

    `status=verified` 必须有可追溯的 `verification` 证据；
    模型给出的主观意见只能记为 candidate，不能直接当作确定性经验。
    """

    lesson_id: str = Field(default_factory=lambda: _new_id("lesson"))
    source_project_id: str = ""
    source_version_id: str = ""
    source_run_id: str = ""
    related_talent: str
    problem: str = Field(min_length=1)
    improvement: str = Field(min_length=1)
    verification: str = ""
    status: LessonStatus = "candidate"
    created_at: datetime = Field(default_factory=_now)

    @model_validator(mode="after")
    def _verified_needs_evidence(self) -> "Lesson":
        if self.status == "verified" and not self.verification.strip():
            raise ValueError("经验标记为 verified 时必须提供 verification 证据")
        return self


class EvolutionProposal(BaseModel):
    """进化提案：只是申请，不会自动生效。"""

    proposal_id: str = Field(default_factory=lambda: _new_id("proposal"))
    target_talent: str
    base_version: int = Field(ge=1)
    candidate_version: int | None = None
    proposed_changes: dict = Field(default_factory=dict)
    supporting_evidence: list[str] = Field(default_factory=list)
    expected_benefit: str = ""
    risks: list[str] = Field(default_factory=list)
    evaluation_status: EvaluationStatus = "pending"
    approval_status: ApprovalStatus = "pending"
    evaluation_id: str | None = None
    generated_by: Literal["rules", "model"] = "rules"
    created_at: datetime = Field(default_factory=_now)
    decided_at: datetime | None = None

    @model_validator(mode="after")
    def _only_allowed_changes(self) -> "EvolutionProposal":
        validate_changes(self.proposed_changes)
        return self


class EvaluationCaseResult(BaseModel):
    """一条回归用例在新旧两版上的表现。"""

    case_id: str
    title: str
    expect_issue: bool
    base_detected: bool = False
    candidate_detected: bool = False
    note: str = ""


class EvaluationMetrics(BaseModel):
    """一版 Talent 在回归集上的指标。"""

    version: int
    expected_cases: int = 0
    detected: int = 0
    detection_rate: float = 0.0
    false_positives: int = 0
    false_positive_rate: float = 0.0
    tokens: int = 0
    token_source: Literal["estimated", "provider", "unknown"] = "estimated"
    duration_ms: int = 0


class AcceptanceCriterion(BaseModel):
    """预先定义的验收条件，评估时逐条比对。"""

    name: str
    threshold: str
    base: float
    candidate: float
    passed: bool


class EvaluationReport(BaseModel):
    """新旧 Talent 的可比较评估结果。"""

    evaluation_id: str = Field(default_factory=lambda: _new_id("eval"))
    proposal_id: str = ""
    target_talent: str
    base_version: int
    candidate_version: int
    engine: EvaluationEngine = "mock"
    cases: list[EvaluationCaseResult] = Field(default_factory=list)
    base: EvaluationMetrics
    candidate: EvaluationMetrics
    acceptance: list[AcceptanceCriterion] = Field(default_factory=list)
    passed: bool = False
    notes: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)

    @property
    def metrics(self) -> dict:
        return {"base": self.base.model_dump(), "candidate": self.candidate.model_dump()}
