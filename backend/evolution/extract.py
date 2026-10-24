"""从已完成任务中提取经验。

判定原则（区分“确定性证据”与“模型推测”）：
- 机械门禁 fail：确定性证据 -> 直接记 verified；
- AI Reviewer 的问题清单：模型意见 -> 只能记 candidate，需要人工补证据后才能 verified；
- 没有 Project / Run 实体，`source_project_id` / `source_run_id` 均映射为 task_id，
  `source_version_id` 记录产物文件名（如有修复历史则指向对应快照）。
"""

from backend.evolution.models import Lesson
from backend.models.contract import TaskRecord
from backend.schemas import MechanicalReport, ReviewReport


def extract_lessons(
    record: TaskRecord,
    artifacts: dict[str, str],
    existing_problems: set[str] | None = None,
) -> list[Lesson]:
    """从 task.json 产物中提取候选/已验证经验，跳过重复问题。"""
    known = set(existing_problems or set())
    lessons: list[Lesson] = []
    version_id = (
        f"history/index.v{record.fix_attempts}.html"
        if record.fix_attempts > 0
        else "index.html"
    )

    gate_raw = artifacts.get("gate.json")
    if gate_raw:
        report = MechanicalReport.model_validate_json(gate_raw)
        for check in report.checks:
            if check.status != "fail":
                continue
            problem = f"机械门禁失败：{check.title}"
            if problem in known:
                continue
            known.add(problem)
            lessons.append(
                Lesson(
                    source_project_id=record.task_id,
                    source_version_id=version_id,
                    source_run_id=record.task_id,
                    related_talent="reviewer",
                    problem=problem,
                    improvement=(
                        f"审查清单新增：给出 PASS 前必须确认「{check.title}」"
                        f"（门禁 id={check.id}）已通过。"
                    ),
                    verification=(
                        f"output/{record.task_id}/gate.json#{check.id} 判定 fail："
                        f"{check.detail[:200]}"
                    ),
                    status="verified",
                )
            )

    review_raw = artifacts.get("review.json")
    if review_raw:
        review = ReviewReport.model_validate_json(review_raw)
        for issue in review.issues:
            if issue.severity == "low":
                continue
            problem = f"审查发现问题：{issue.description[:120]}"
            if problem in known:
                continue
            known.add(problem)
            lessons.append(
                Lesson(
                    source_project_id=record.task_id,
                    source_version_id=version_id,
                    source_run_id=record.task_id,
                    related_talent="engineer",
                    problem=problem,
                    improvement=f"实现清单新增：{issue.suggestion[:200]}",
                    verification="",
                    status="candidate",
                )
            )

    return lessons
