"""固定回归用例与新旧 Talent 对比评估。

评估引擎说明（重要）：
- `mock`：根据“检查清单/提示词是否显式覆盖该缺陷的验证点”做确定性判定。
  它是流程与回归集的模拟，**不代表真实模型能力**，报告里会明确标注。
- `live`：真实模型评估尚未接入本阶段，服务层会直接拒绝，避免伪造真实评测结果。

验收条件在 `ACCEPTANCE_CRITERIA` 中预先写死，评估只能逐条比对，不能事后调整。
"""

from time import perf_counter

from backend.evolution.models import (
    AcceptanceCriterion,
    EvaluationCaseResult,
    EvaluationMetrics,
    EvaluationReport,
    TalentVersion,
)

# 预定义验收条件（阈值写死在代码里，提案不能修改）
ACCEPTANCE_CRITERIA = {
    "detection_min": 0.9,
    "false_positive_max": 0.1,
    "token_ratio_max": 2.0,
}


class RegressionCase:
    """一条固定回归用例。

    `coverage_groups`：需要全部覆盖的关键词组，任意一组内命中一个关键词即可。
    `overreach_groups`：如果候选版本出现这些组合，视为对正常样例的误报。
    """

    def __init__(
        self,
        case_id: str,
        title: str,
        expect_issue: bool,
        improvement: str,
        coverage_groups: tuple[tuple[str, ...], ...] = (),
        overreach_groups: tuple[tuple[str, ...], ...] = (),
    ) -> None:
        self.case_id = case_id
        self.title = title
        self.expect_issue = expect_issue
        self.improvement = improvement
        self.coverage_groups = coverage_groups
        self.overreach_groups = overreach_groups


CASES: dict[str, tuple[RegressionCase, ...]] = {
    "reviewer": (
        RegressionCase(
            "normal_game",
            "正常游戏：应给出 PASS，不应误报",
            expect_issue=False,
            improvement="",
            overreach_groups=(("一律 iterate", "全部拒绝"),),
        ),
        RegressionCase(
            "restart_broken",
            "重新开始失效：游戏结束后点击重新开始无响应",
            expect_issue=True,
            improvement="审查清单新增：验证游戏结束后点击重新开始，状态与分数正确重置。",
            coverage_groups=(("重新开始", "重开", "restart"),),
        ),
        RegressionCase(
            "pause_broken",
            "暂停失效：暂停后游戏仍在运行",
            expect_issue=True,
            improvement="审查清单新增：验证暂停可冻结游戏循环，恢复后继续。",
            coverage_groups=(("暂停", "pause"),),
        ),
        RegressionCase(
            "score_wrong",
            "得分错误：吃到目标后计分不增加或重复计分",
            expect_issue=True,
            improvement="审查清单新增：验证每次得分事件只计一次，分数与状态同步更新。",
            coverage_groups=(("得分", "计分", "score"),),
        ),
        RegressionCase(
            "js_error",
            "JavaScript 报错：控制台存在未捕获异常",
            expect_issue=True,
            improvement="审查清单新增：检查控制台是否存在未处理 JS 异常，存在即判 ITERATE。",
            coverage_groups=(("js",), ("报错", "异常", "错误")),
        ),
    ),
    "coo": (
        RegressionCase(
            "normal_requirement",
            "正常需求：应输出完整 PRD",
            expect_issue=False,
            improvement="",
            overreach_groups=(("一律拒绝",),),
        ),
        RegressionCase(
            "missing_acceptance",
            "缺少验收标准：PRD 无法机械验证",
            expect_issue=True,
            improvement="PRD 清单新增：每条功能必须给出可机械验证的验收标准。",
            coverage_groups=(("验收",), ("标准", "条件")),
        ),
        RegressionCase(
            "missing_lose_condition",
            "缺少失败条件：游戏没有结束判定",
            expect_issue=True,
            improvement="PRD 清单新增：必须描述胜利与失败条件及触发方式。",
            coverage_groups=(("失败条件", "lose"),),
        ),
        RegressionCase(
            "vague_core_loop",
            "核心循环模糊：无法据此实现",
            expect_issue=True,
            improvement="PRD 清单新增：核心循环必须描述输入、更新、反馈三步。",
            coverage_groups=(("核心循环", "core loop"),),
        ),
    ),
    "engineer": (
        RegressionCase(
            "game_normal",
            "正常游戏：单文件可运行",
            expect_issue=False,
            improvement="",
            overreach_groups=(("一律重写",),),
        ),
        RegressionCase(
            "no_restart",
            "缺少重新开始入口",
            expect_issue=True,
            improvement="实现清单新增：必须提供重新开始入口并重置分数与状态。",
            coverage_groups=(("重新开始", "重开", "restart"),),
        ),
        RegressionCase(
            "no_score",
            "计分未实现或未刷新",
            expect_issue=True,
            improvement="实现清单新增：得分变化必须同步刷新界面。",
            coverage_groups=(("计分", "得分", "score"),),
        ),
        RegressionCase(
            "js_error",
            "存在未处理 JS 异常",
            expect_issue=True,
            improvement="实现清单新增：提交前自检控制台无未捕获异常。",
            coverage_groups=(("js",), ("报错", "异常", "错误")),
        ),
    ),
    "backup_engineer": (
        RegressionCase(
            "game_normal",
            "正常游戏：单文件可运行",
            expect_issue=False,
            improvement="",
            overreach_groups=(("一律重写",),),
        ),
        RegressionCase(
            "no_restart",
            "缺少重新开始入口",
            expect_issue=True,
            improvement="实现清单新增：必须提供重新开始入口并重置分数与状态。",
            coverage_groups=(("重新开始", "重开", "restart"),),
        ),
        RegressionCase(
            "no_score",
            "计分未实现或未刷新",
            expect_issue=True,
            improvement="实现清单新增：得分变化必须同步刷新界面。",
            coverage_groups=(("计分", "得分", "score"),),
        ),
        RegressionCase(
            "js_error",
            "存在未处理 JS 异常",
            expect_issue=True,
            improvement="实现清单新增：提交前自检控制台无未捕获异常。",
            coverage_groups=(("js",), ("报错", "异常", "错误")),
        ),
    ),
    "marketer": (
        RegressionCase(
            "kit_normal",
            "正常素材：只宣传已验证功能",
            expect_issue=False,
            improvement="",
            overreach_groups=(("一律删除",),),
        ),
        RegressionCase(
            "fabricated_users",
            "编造用户数或下载量",
            expect_issue=True,
            improvement="文案清单新增：禁止出现任何用户数、下载量、留存等编造数据。",
            coverage_groups=(("用户数", "下载量"),),
        ),
        RegressionCase(
            "unverified_feature",
            "宣传未经门禁验证的功能",
            expect_issue=True,
            improvement="文案清单新增：只能宣传机械门禁已验证的功能，未验证功能不得提及。",
            coverage_groups=(("未验证",), ("不得", "不能", "禁止")),
        ),
        RegressionCase(
            "missing_plan",
            "缺少 7 天推广计划",
            expect_issue=True,
            improvement="文案清单新增：必须输出 7 天推广计划与 2 篇小红书文案。",
            coverage_groups=(("7 天", "七天", "推广计划"),),
        ),
    ),
    "creative": (
        RegressionCase(
            "normal_requirement",
            "正常需求：应给出可执行的创意建议",
            expect_issue=False,
            improvement="",
            overreach_groups=(("一律拒绝", "全部否定"),),
        ),
        RegressionCase(
            "missing_player_value",
            "缺少玩家价值：无法回答为什么值得体验",
            expect_issue=True,
            improvement="创意清单新增：必须说明建议对玩家的具体价值。",
            coverage_groups=(("玩家价值", "player value"),),
        ),
        RegressionCase(
            "missing_rationale",
            "缺少依据：建议无法追溯",
            expect_issue=True,
            improvement="创意清单新增：每条建议必须给出基于事实的依据。",
            coverage_groups=(("依据", "rationale"),),
        ),
        RegressionCase(
            "drama_conflict",
            "为戏剧效果刻意反对",
            expect_issue=True,
            improvement="创意清单新增：不得为了戏剧效果刻意唱反调，认同时应明确说明。",
            coverage_groups=(("戏剧", "刻意反对"),),
        ),
    ),
    "delivery": (
        RegressionCase(
            "normal_requirement",
            "正常需求：创意可交付时不应强行否定",
            expect_issue=False,
            improvement="",
            overreach_groups=(("一律拒绝", "全部否定"),),
        ),
        RegressionCase(
            "missing_risk",
            "缺少最大交付风险",
            expect_issue=True,
            improvement="交付清单新增：必须指出最大交付风险。",
            coverage_groups=(("风险", "risk"),),
        ),
        RegressionCase(
            "missing_feasibility",
            "缺少可行性判断",
            expect_issue=True,
            improvement="交付清单新增：必须给出可行的可行性判断与依据。",
            coverage_groups=(("可行性", "feasibility"),),
        ),
        RegressionCase(
            "drama_conflict",
            "为戏剧效果刻意反对",
            expect_issue=True,
            improvement="交付清单新增：不得为了戏剧效果刻意唱反调，可交付时明确判定 feasible。",
            coverage_groups=(("戏剧", "刻意反对"),),
        ),
    ),
}


def cases_for(talent: str) -> tuple[RegressionCase, ...]:
    return CASES.get(talent, ())


def _text_of(version: TalentVersion) -> str:
    return "\n".join([version.prompt, *version.checklist]).lower()


def _covers(text: str, groups: tuple[tuple[str, ...], ...]) -> bool:
    if not groups:
        return False
    return all(any(word.lower() in text for word in group) for group in groups)


def _detects(text: str, case: RegressionCase) -> bool:
    return _covers(text, case.coverage_groups)


def _metrics(
    version: TalentVersion, text: str, cases: tuple[RegressionCase, ...], duration_ms: int
) -> EvaluationMetrics:
    expected = [case for case in cases if case.expect_issue]
    detected = sum(1 for case in expected if _detects(text, case))
    normal = [case for case in cases if not case.expect_issue]
    false_positives = sum(1 for case in normal if _covers(text, case.overreach_groups))
    return EvaluationMetrics(
        version=version.version,
        expected_cases=len(expected),
        detected=detected,
        detection_rate=round(detected / len(expected), 4) if expected else 0.0,
        false_positives=false_positives,
        false_positive_rate=round(false_positives / len(normal), 4) if normal else 0.0,
        tokens=len(text) // 4 * len(cases),
        token_source="estimated",
        duration_ms=duration_ms,
    )


def evaluate_versions(
    talent: str,
    base: TalentVersion,
    candidate: TalentVersion,
    *,
    engine: str = "mock",
    proposal_id: str = "",
) -> EvaluationReport:
    """在同一组固定用例上对比新旧两版 Talent。"""
    cases = cases_for(talent)
    if not cases:
        raise ValueError(f"{talent} 没有配置固定回归用例")

    started = perf_counter()
    base_text = _text_of(base)
    candidate_text = _text_of(candidate)
    results: list[EvaluationCaseResult] = []
    for case in cases:
        results.append(
            EvaluationCaseResult(
                case_id=case.case_id,
                title=case.title,
                expect_issue=case.expect_issue,
                base_detected=_detects(base_text, case),
                candidate_detected=_detects(candidate_text, case),
                note="" if case.expect_issue else "正常样例：用于检查误报",
            )
        )
    duration_ms = int((perf_counter() - started) * 1000)

    base_metrics = _metrics(base, base_text, cases, duration_ms)
    candidate_metrics = _metrics(candidate, candidate_text, cases, duration_ms)

    token_ratio = (
        candidate_metrics.tokens / base_metrics.tokens
        if base_metrics.tokens
        else float("inf")
    )
    acceptance = [
        AcceptanceCriterion(
            name="检出率达标",
            threshold=f">= {ACCEPTANCE_CRITERIA['detection_min']}",
            base=base_metrics.detection_rate,
            candidate=candidate_metrics.detection_rate,
            passed=candidate_metrics.detection_rate
            >= ACCEPTANCE_CRITERIA["detection_min"],
        ),
        AcceptanceCriterion(
            name="检出率不低于基线",
            threshold="candidate >= base",
            base=base_metrics.detection_rate,
            candidate=candidate_metrics.detection_rate,
            passed=candidate_metrics.detection_rate >= base_metrics.detection_rate,
        ),
        AcceptanceCriterion(
            name="误报率可接受",
            threshold=f"<= {ACCEPTANCE_CRITERIA['false_positive_max']}",
            base=base_metrics.false_positive_rate,
            candidate=candidate_metrics.false_positive_rate,
            passed=candidate_metrics.false_positive_rate
            <= ACCEPTANCE_CRITERIA["false_positive_max"],
        ),
        AcceptanceCriterion(
            name="Token 消耗可控",
            threshold=f"<= {ACCEPTANCE_CRITERIA['token_ratio_max']}x base",
            base=base_metrics.tokens,
            candidate=candidate_metrics.tokens,
            passed=token_ratio <= ACCEPTANCE_CRITERIA["token_ratio_max"],
        ),
    ]

    notes = [
        f"回归用例：{len(cases)} 条（需检出 {base_metrics.expected_cases} 条，正常样例 {len(cases) - base_metrics.expected_cases} 条）",
        "Token 数为按字符数估算（estimated），非供应商账单",
    ]
    if engine == "mock":
        notes.append(
            "引擎=mock：判定依据是检查清单是否显式覆盖缺陷验证点，属确定性模拟，不代表真实模型能力"
        )
    else:
        notes.append("引擎=live：由真实模型执行同一组用例")

    return EvaluationReport(
        proposal_id=proposal_id,
        target_talent=talent,
        base_version=base.version,
        candidate_version=candidate.version,
        engine="mock" if engine == "mock" else "live",
        cases=results,
        base=base_metrics,
        candidate=candidate_metrics,
        acceptance=acceptance,
        passed=all(item.passed for item in acceptance),
        notes=notes,
    )
