"""自进化服务：把存储、回归评估与用户审批串成完整闭环。

闭环各步的硬性约束：
1. 诊断只能从**确定性回归结果**生成 verified 经验；
2. 提案只接受 verified 经验，且只能改提示词/检查清单；
3. 提案必须先在固定回归集上与基线对比并通过预定义验收条件；
4. 只有用户显式批准后，候选版本才能启用；
5. 任何历史版本都可回滚，启用审计写入 active.json。
"""

from datetime import datetime, timezone

from backend.evolution.errors import EvolutionError, EvolutionStateError
from backend.evolution.extract import extract_lessons
from backend.evolution.models import (
    EvaluationReport,
    EvolutionProposal,
    Lesson,
    TalentVersion,
)
from backend.evolution.regression import (
    ACCEPTANCE_CRITERIA,
    cases_for,
    evaluate_versions,
)
from backend.evolution.store import EvolutionStore
from backend.models.contract import TaskRecord


class EvolutionService:
    def __init__(self, store: EvolutionStore, *, mock_mode: bool = True) -> None:
        self.store = store
        self.mock_mode = mock_mode

    def _engine(self) -> str:
        """当前可用的评估引擎。

        真实模型评估尚未接入：宁可明确报错，也不要用模拟结果冒充真实评测。
        """
        if not self.mock_mode:
            raise EvolutionError(
                "真实模型评估尚未接入（阶段 8 仅提供 MOCK_MODE=true 的确定性回归评估），"
                "拒绝伪造真实模型评测结果"
            )
        return "mock"

    # ---------- 查询 ----------

    def talents(self) -> list[dict]:
        items = []
        for name in self.store.talent_names():
            baseline = self.store.baseline(name)
            active = self.store.active_version(name)
            items.append(
                {
                    "talent_name": name,
                    "name": baseline.name,
                    "role": baseline.role,
                    "active_version": active.version,
                    "active_label": active.label,
                    "versions": len(self.store.versions(name)),
                }
            )
        return items

    def detail(self, talent: str) -> dict:
        active = self.store.active_version(talent)
        baseline = self.store.baseline(talent)
        lessons = self.store.list_lessons(talent)
        proposals = self.store.list_proposals(talent)
        evaluations = [
            item
            for item in self.store.list_evaluations()
            if item.target_talent == talent
        ]
        return {
            "talent_name": talent,
            "name": baseline.name,
            "role": baseline.role,
            "active_version": active.model_dump(mode="json"),
            "versions": [
                item.model_dump(mode="json")
                for item in reversed(self.store.versions(talent))
            ],
            "audit": self.store.audit_log(talent),
            "lessons": [item.model_dump(mode="json") for item in lessons],
            "proposals": [
                item.model_dump(mode="json") for item in reversed(proposals)
            ],
            "evaluations": [
                item.model_dump(mode="json") for item in reversed(evaluations)
            ],
            "regression_cases": [
                {
                    "case_id": case.case_id,
                    "title": case.title,
                    "expect_issue": case.expect_issue,
                }
                for case in cases_for(talent)
            ],
            "acceptance_criteria": ACCEPTANCE_CRITERIA,
        }

    # ---------- 经验 ----------

    def lessons_from_task(
        self, record: TaskRecord, artifacts: dict[str, str]
    ) -> list[Lesson]:
        existing = {item.problem for item in self.store.list_lessons()}
        lessons = extract_lessons(record, artifacts, existing)
        return [self.store.add_lesson(item) for item in lessons]

    def verify_lesson(self, lesson_id: str, verification: str) -> Lesson:
        lesson = self.store.get_lesson(lesson_id)
        if lesson.status != "candidate":
            raise EvolutionStateError(f"经验 {lesson_id} 当前状态为 {lesson.status}，不能验证")
        if not verification.strip():
            raise EvolutionError("验证经验必须提供可追溯的证据")
        updated = Lesson.model_validate(
            {
                **lesson.model_dump(),
                "status": "verified",
                "verification": verification.strip(),
            }
        )
        return self.store.update_lesson(updated)

    def reject_lesson(self, lesson_id: str) -> Lesson:
        lesson = self.store.get_lesson(lesson_id)
        if lesson.status == "verified":
            raise EvolutionStateError("已验证经验不能直接拒绝，请说明后人工处理")
        updated = Lesson.model_validate({**lesson.model_dump(), "status": "rejected"})
        return self.store.update_lesson(updated)

    # ---------- 诊断 ----------

    def diagnose(self, talent: str) -> tuple[EvaluationReport, list[Lesson]]:
        """用固定回归集诊断当前启用版本，漏检项直接生成 verified 经验。"""
        base = self.store.active_version(talent)
        engine = self._engine()
        report = evaluate_versions(talent, base, base, engine=engine)
        report.notes.append("基线诊断：candidate 与 base 相同，用于暴露当前版本的漏检项")
        report = self.store.save_evaluation(report)

        existing = {item.problem for item in self.store.list_lessons(talent)}
        created: list[Lesson] = []
        for case, result in zip(cases_for(talent), report.cases):
            if not case.expect_issue or result.base_detected:
                continue
            problem = f"回归漏检：{case.title}"
            if problem in existing:
                continue
            existing.add(problem)
            created.append(
                self.store.add_lesson(
                    Lesson(
                        source_project_id="regression-suite",
                        source_version_id=base.label,
                        source_run_id=report.evaluation_id,
                        related_talent=talent,
                        problem=problem,
                        improvement=case.improvement,
                        verification=(
                            f"回归评估 {report.evaluation_id}#{case.case_id} 未检出"
                            f"（engine={report.engine}）"
                        ),
                        status="verified",
                    )
                )
            )
        return report, created

    # ---------- 提案 ----------

    def create_proposal(
        self, talent: str, lesson_ids: list[str]
    ) -> tuple[EvolutionProposal, TalentVersion]:
        if not lesson_ids:
            raise EvolutionError("至少需要一条已验证经验才能生成提案")
        base = self.store.active_version(talent)
        lessons = [self.store.get_lesson(item) for item in lesson_ids]
        for lesson in lessons:
            if lesson.related_talent != talent:
                raise EvolutionError(
                    f"经验 {lesson.lesson_id} 属于 {lesson.related_talent}，不能用于 {talent}"
                )
            if lesson.status != "verified":
                raise EvolutionStateError(
                    f"经验 {lesson.lesson_id} 状态为 {lesson.status}，只有 verified 经验才能进入提案"
                )

        used: set[str] = set()
        for proposal in self.store.list_proposals(talent):
            if proposal.approval_status != "rejected":
                used.update(proposal.supporting_evidence)
        duplicated = used.intersection(lesson_ids)
        if duplicated:
            raise EvolutionStateError(f"这些经验已被其他提案使用：{sorted(duplicated)}")

        additions: list[str] = []
        for lesson in lessons:
            item = lesson.improvement.strip()
            if item and item not in base.checklist and item not in additions:
                additions.append(item)
        if not additions:
            raise EvolutionStateError("这些经验已包含在当前检查清单中，无需进化")

        checklist = [*base.checklist, *additions]
        # 规则型提案只追加检查清单，不改写提示词：来源可追溯，也不放大 token 消耗。
        # 提示词级改写需要真实模型评估（本阶段未接入），避免未经评估的文案直接生效。
        prompt = base.prompt
        proposal = EvolutionProposal(
            target_talent=talent,
            base_version=base.version,
            proposed_changes={"prompt": prompt, "checklist": checklist},
            supporting_evidence=[lesson.lesson_id for lesson in lessons],
            expected_benefit=(
                f"在固定回归集上覆盖 {len(additions)} 个已验证缺陷场景，"
                f"目标检出率 >= {ACCEPTANCE_CRITERIA['detection_min']}"
            ),
            risks=[
                "提示词变长会增加 token 消耗",
                "新增检查项可能带来误报，需要评估误报率",
                "进化不触碰工具权限、输出契约、模型与质量门禁",
            ],
        )
        candidate = self.store.create_candidate(
            talent,
            prompt=prompt,
            checklist=checklist,
            change_reason="吸收已验证经验：" + "；".join(item.problem for item in lessons),
            proposal_id=proposal.proposal_id,
        )
        proposal = proposal.model_copy(
            update={"candidate_version": candidate.version}
        )
        self.store.save_proposal(proposal)
        return proposal, candidate

    # ---------- 评估与审批 ----------

    def evaluate(self, proposal_id: str) -> EvaluationReport:
        proposal = self.store.get_proposal(proposal_id)
        if proposal.approval_status != "pending":
            raise EvolutionStateError("提案已审批，不能重新评估")
        if proposal.candidate_version is None:
            raise EvolutionStateError("提案缺少候选版本")
        base = self.store.version(
            proposal.target_talent, proposal.base_version
        )
        candidate = self.store.version(
            proposal.target_talent, proposal.candidate_version
        )
        report = evaluate_versions(
            proposal.target_talent,
            base,
            candidate,
            engine=self._engine(),
            proposal_id=proposal_id,
        )
        self.store.save_evaluation(report)
        self.store.set_version_evaluation(
            candidate,
            f"{report.evaluation_id}:{'passed' if report.passed else 'failed'}",
        )
        proposal = proposal.model_copy(
            update={
                "evaluation_status": "passed" if report.passed else "failed",
                "evaluation_id": report.evaluation_id,
            }
        )
        self.store.save_proposal(proposal)
        return report

    def approve(self, proposal_id: str) -> tuple[EvolutionProposal, TalentVersion]:
        proposal = self.store.get_proposal(proposal_id)
        if proposal.approval_status != "pending":
            raise EvolutionStateError("提案已审批，不能重复批准")
        if proposal.evaluation_status != "passed":
            raise EvolutionStateError("提案评估未通过，不能批准")
        if proposal.candidate_version is None:
            raise EvolutionStateError("提案缺少候选版本")

        # 先落盘“已批准”，再由存储层做启用校验；启用失败则回滚审批状态，避免半生效
        approved = proposal.model_copy(
            update={
                "approval_status": "approved",
                "decided_at": datetime.now(timezone.utc),
            }
        )
        self.store.save_proposal(approved)
        try:
            activated = self.store.activate(
                proposal.target_talent,
                proposal.candidate_version,
                reason=f"用户批准进化提案 {proposal_id}",
                proposal_id=proposal_id,
            )
        except Exception:
            self.store.save_proposal(proposal)
            raise
        return approved, activated

    def reject_proposal(self, proposal_id: str) -> EvolutionProposal:
        proposal = self.store.get_proposal(proposal_id)
        if proposal.approval_status != "pending":
            raise EvolutionStateError("提案已审批，不能重复拒绝")
        if proposal.candidate_version is not None:
            candidate = self.store.version(
                proposal.target_talent, proposal.candidate_version
            )
            self.store.reject_version(candidate)
        proposal = proposal.model_copy(
            update={
                "approval_status": "rejected",
                "decided_at": datetime.now(timezone.utc),
            }
        )
        self.store.save_proposal(proposal)
        return proposal

    def rollback(
        self, talent: str, version: int, reason: str = ""
    ) -> TalentVersion:
        target = self.store.version(talent, version)
        if target.status == "candidate":
            raise EvolutionStateError("候选版本不能直接启用，必须先评估并获得批准")
        return self.store.activate(
            talent,
            version,
            reason=reason or f"用户回滚到 {target.label}",
            proposal_id=None,
        )
