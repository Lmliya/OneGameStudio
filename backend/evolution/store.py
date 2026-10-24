"""自进化的文件存储。

目录结构（默认 `output/evolution/`，可通过 `EVOLUTION_DIR` 配置）：

    talents/{talent}/versions/v{n}.json   不可变版本快照（只增不改内容）
    talents/{talent}/active.json          当前启用版本指针 + 启用审计日志
    lessons/{lesson_id}.json              经验库
    proposals/{proposal_id}.json          进化提案
    evaluations/{evaluation_id}.json      新旧 Talent 评估报告

没有数据库：所有状态都是可读 JSON，便于人工审计与回滚。
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from backend.evolution.errors import (
    EvolutionError,
    EvolutionStateError,
    ImmutableFieldError,
    VersionNotFoundError,
)
from backend.evolution.models import (
    EvaluationReport,
    EvolutionProposal,
    Lesson,
    TalentVersion,
    validate_changes,
)
from backend.models.talent import TalentSpec
from backend.talents import list_talents, load_talent


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EvolutionStore:
    """Talent 版本、经验、提案与评估的持久化入口。"""

    def __init__(self, root: Path, talents_dir: Path) -> None:
        self.root = Path(root)
        self.talents_dir = Path(talents_dir)

    # ---------- 基础读写 ----------

    def _talent_dir(self, name: str) -> Path:
        return self.root / "talents" / name

    def _version_path(self, name: str, version: int) -> Path:
        return self._talent_dir(name) / "versions" / f"v{version}.json"

    def _active_path(self, name: str) -> Path:
        return self._talent_dir(name) / "active.json"

    @staticmethod
    def _read(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(path)

    # ---------- 基线 Talent ----------

    def baseline(self, name: str) -> TalentSpec:
        return load_talent(name, self.talents_dir)

    def talent_names(self) -> list[str]:
        return sorted(list_talents(self.talents_dir))

    def ensure_seeded(self) -> None:
        """把每个基线 YAML 注册为 v1（已有 active.json 则跳过）。"""
        if not self.talents_dir.exists():
            return
        for name in list_talents(self.talents_dir):
            if self._active_path(name).exists():
                continue
            self._seed_talent(name)

    def _seed_talent(self, name: str) -> None:
        """为单个 Talent 补齐 v1 快照与 active.json 指针。

        版本库可能被人工清理（例如删除 output/），因此这里不能假设
        “启动时 seed 过就永远存在”：v1 文件已存在时保留原内容，
        只补写缺失的 active.json，避免覆盖历史版本。
        """
        spec = self.baseline(name)
        version_path = self._version_path(name, 1)
        if not version_path.exists():
            version = TalentVersion(
                talent_name=name,
                version=1,
                parent_version=None,
                prompt=spec.system_prompt,
                checklist=list(spec.checklist),
                change_reason="基线版本（来自 talents/*.yaml）",
                evaluation_result=None,
                status="active",
                allowed_tools=list(spec.allowed_tools),
                output_schema=spec.output_schema,
                model=spec.model,
            )
            self._write(version_path, version.model_dump(mode="json"))
        self._write(
            self._active_path(name),
            {
                "talent_name": name,
                "active_version": 1,
                "updated_at": _now_iso(),
                "audit": [
                    {
                        "at": _now_iso(),
                        "action": "seed",
                        "from_version": None,
                        "to_version": 1,
                        "reason": "基线注册",
                        "proposal_id": None,
                    }
                ],
            },
        )

    # ---------- 版本 ----------

    def versions(self, name: str) -> list[TalentVersion]:
        folder = self._talent_dir(name) / "versions"
        if not folder.exists():
            return []
        items = [
            TalentVersion.model_validate(self._read(path))
            for path in folder.glob("v*.json")
        ]
        return sorted(items, key=lambda item: item.version)

    def version(self, name: str, version: int) -> TalentVersion:
        path = self._version_path(name, version)
        if not path.exists():
            raise VersionNotFoundError(f"{name} 不存在版本 v{version}")
        return TalentVersion.model_validate(self._read(path))

    def active_version(self, name: str) -> TalentVersion:
        active_path = self._active_path(name)
        if not active_path.exists():
            # 自愈：版本库被清理后按基线重建，避免整个任务因缺指针而失败
            self.ensure_seeded()
        if not active_path.exists():
            raise VersionNotFoundError(f"{name} 尚未注册任何 Talent 版本")
        active = self._read(active_path)["active_version"]
        return self.version(name, int(active))

    def effective_spec(self, name: str) -> TalentSpec:
        """基线权限 + 当前启用版本的提示词与检查清单。"""
        baseline = self.baseline(name)
        version = self.active_version(name)
        return baseline.model_copy(
            update={
                "system_prompt": version.prompt,
                "checklist": list(version.checklist),
                "version": version.version,
            }
        )

    def create_candidate(
        self,
        name: str,
        *,
        prompt: str,
        checklist: list[str],
        change_reason: str,
        proposal_id: str,
    ) -> TalentVersion:
        """基于当前启用版本创建候选版本；安全边界字段从基线复制。"""
        validate_changes({"prompt": prompt, "checklist": checklist})
        if not prompt.strip():
            raise EvolutionStateError("候选版本的提示词不能为空")
        baseline = self.baseline(name)
        existing = self.versions(name)
        next_version = (existing[-1].version if existing else 0) + 1
        candidate = TalentVersion(
            talent_name=name,
            version=next_version,
            parent_version=self.active_version(name).version,
            prompt=prompt,
            checklist=list(checklist),
            change_reason=change_reason,
            status="candidate",
            proposal_id=proposal_id,
            allowed_tools=list(baseline.allowed_tools),
            output_schema=baseline.output_schema,
            model=baseline.model,
        )
        path = self._version_path(name, next_version)
        if path.exists():
            raise EvolutionStateError(f"版本文件已存在，拒绝覆盖：{path}")
        self._write(path, candidate.model_dump(mode="json"))
        return candidate

    def _set_version_status(self, version: TalentVersion, status: str) -> TalentVersion:
        """只允许改状态，内容必须保持不变。"""
        updated = version.model_copy(update={"status": status})
        self._write(
            self._version_path(version.talent_name, version.version),
            updated.model_dump(mode="json"),
        )
        return updated

    def set_version_evaluation(
        self, version: TalentVersion, result: str
    ) -> TalentVersion:
        updated = version.model_copy(update={"evaluation_result": result})
        self._write(
            self._version_path(version.talent_name, version.version),
            updated.model_dump(mode="json"),
        )
        return updated

    def reject_version(self, version: TalentVersion) -> TalentVersion:
        if version.status == "active":
            raise EvolutionStateError(f"{version.label} 正在启用中，不能直接标记为拒绝")
        return self._set_version_status(version, "rejected")

    def activate(
        self,
        name: str,
        version: int,
        *,
        reason: str,
        proposal_id: str | None = None,
    ) -> TalentVersion:
        """启用某一版本。

        规则：
        - 候选版本必须已有“评估通过 + 用户批准”的提案；
        - 历史非候选版本可以启用（回滚），但拒绝已否决版本；
        - 工具白名单 / 输出契约 / 模型必须与基线一致，否则拒绝启用。
        """
        target = self.version(name, version)
        baseline = self.baseline(name)
        self._assert_safe_boundary(target, baseline)

        if target.status == "rejected":
            raise EvolutionStateError(f"{target.label} 已被拒绝，不能启用")

        if target.status == "candidate":
            if not proposal_id:
                raise EvolutionStateError("候选版本必须由已批准的进化提案启用")
            proposal = self.get_proposal(proposal_id)
            if proposal.candidate_version != version:
                raise EvolutionStateError("提案与候选版本不匹配")
            if proposal.approval_status != "approved":
                raise EvolutionStateError("提案尚未获得用户批准，不能启用")
            if proposal.evaluation_status != "passed":
                raise EvolutionStateError("提案评估未通过，不能启用")

        active_path = self._active_path(name)
        if not active_path.exists():
            self.ensure_seeded()
        if not active_path.exists():
            raise VersionNotFoundError(f"{name} 尚未注册任何 Talent 版本")
        active = self._read(active_path)
        previous = int(active["active_version"])
        if previous == version:
            return target

        previous_version = self.version(name, previous)
        if previous_version.status == "active":
            self._set_version_status(previous_version, "inactive")
        self._set_version_status(target, "active")

        audit = list(active.get("audit", []))
        audit.append(
            {
                "at": _now_iso(),
                "action": "rollback" if proposal_id is None else "activate",
                "from_version": previous,
                "to_version": version,
                "reason": reason,
                "proposal_id": proposal_id,
            }
        )
        self._write(
            active_path,
            {
                "talent_name": name,
                "active_version": version,
                "updated_at": _now_iso(),
                "audit": audit,
            },
        )
        return self.version(name, version)

    def audit_log(self, name: str) -> list[dict]:
        path = self._active_path(name)
        if not path.exists():
            return []
        return list(self._read(path).get("audit", []))

    @staticmethod
    def _assert_safe_boundary(version: TalentVersion, baseline: TalentSpec) -> None:
        if list(version.allowed_tools) != list(baseline.allowed_tools):
            raise ImmutableFieldError(
                f"{version.label} 的工具白名单与基线不一致，拒绝启用"
            )
        if version.output_schema != baseline.output_schema:
            raise ImmutableFieldError(
                f"{version.label} 的输出契约与基线不一致，拒绝启用"
            )
        if version.model != baseline.model:
            raise ImmutableFieldError(
                f"{version.label} 的模型配置与基线不一致，拒绝启用"
            )

    # ---------- 经验库 ----------

    def add_lesson(self, lesson: Lesson) -> Lesson:
        path = self.root / "lessons" / f"{lesson.lesson_id}.json"
        if path.exists():
            raise EvolutionStateError(f"经验已存在：{lesson.lesson_id}")
        self._write(path, lesson.model_dump(mode="json"))
        return lesson

    def get_lesson(self, lesson_id: str) -> Lesson:
        path = self.root / "lessons" / f"{lesson_id}.json"
        if not path.exists():
            raise EvolutionError(f"经验不存在：{lesson_id}")
        return Lesson.model_validate(self._read(path))

    def list_lessons(self, talent: str | None = None) -> list[Lesson]:
        folder = self.root / "lessons"
        if not folder.exists():
            return []
        lessons = [
            Lesson.model_validate(self._read(path)) for path in folder.glob("*.json")
        ]
        if talent:
            lessons = [item for item in lessons if item.related_talent == talent]
        return sorted(lessons, key=lambda item: item.created_at)

    def update_lesson(self, lesson: Lesson) -> Lesson:
        path = self.root / "lessons" / f"{lesson.lesson_id}.json"
        if not path.exists():
            raise EvolutionError(f"经验不存在：{lesson.lesson_id}")
        self._write(path, lesson.model_dump(mode="json"))
        return lesson

    # ---------- 提案 ----------

    def save_proposal(self, proposal: EvolutionProposal) -> EvolutionProposal:
        self._write(
            self.root / "proposals" / f"{proposal.proposal_id}.json",
            proposal.model_dump(mode="json"),
        )
        return proposal

    def get_proposal(self, proposal_id: str) -> EvolutionProposal:
        path = self.root / "proposals" / f"{proposal_id}.json"
        if not path.exists():
            raise EvolutionError(f"提案不存在：{proposal_id}")
        return EvolutionProposal.model_validate(self._read(path))

    def list_proposals(self, talent: str | None = None) -> list[EvolutionProposal]:
        folder = self.root / "proposals"
        if not folder.exists():
            return []
        items = [
            EvolutionProposal.model_validate(self._read(path))
            for path in folder.glob("*.json")
        ]
        if talent:
            items = [item for item in items if item.target_talent == talent]
        return sorted(items, key=lambda item: item.created_at)

    # ---------- 评估 ----------

    def save_evaluation(self, report: EvaluationReport) -> EvaluationReport:
        self._write(
            self.root / "evaluations" / f"{report.evaluation_id}.json",
            report.model_dump(mode="json"),
        )
        return report

    def get_evaluation(self, evaluation_id: str) -> EvaluationReport:
        path = self.root / "evaluations" / f"{evaluation_id}.json"
        if not path.exists():
            raise EvolutionError(f"评估报告不存在：{evaluation_id}")
        return EvaluationReport.model_validate(self._read(path))

    def list_evaluations(self) -> list[EvaluationReport]:
        folder = self.root / "evaluations"
        if not folder.exists():
            return []
        items = [
            EvaluationReport.model_validate(self._read(path))
            for path in folder.glob("*.json")
        ]
        return sorted(items, key=lambda item: item.created_at)
