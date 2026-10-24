"""SOP 模式与冲突决策的共享模型。

这些类型同时被任务记录、版本记录与输出契约引用，放在独立模块避免循环依赖。
"""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class SOPMode(str, Enum):
    """三种标准作业流程。FAST 只做局部修改，BALANCED 常规开发，CREATIVE 允许额外修订。"""

    FAST = "fast"
    BALANCED = "balanced"
    CREATIVE = "creative"


class ConflictDecision(BaseModel):
    """COO 对创意与交付意见的最终裁决。

    rationale 必填：没有理由的决策不能落盘，也不能进入编码阶段。
    """

    decision: Literal["adopt", "simplify", "reject"]
    summary: str = Field(min_length=1, description="对双方观点的汇总")
    rationale: str = Field(min_length=1, description="为什么这样裁决")
    adopted_from: Literal["creative", "delivery", "both", "neither"] = "both"


class RunMetrics(BaseModel):
    """一次 Run 的实际执行指标；全部来自真实计时与调用计数，不做推算。"""

    elapsed_ms: int = Field(default=0, ge=0, description="整个 Run 的墙钟耗时")
    model_calls: int = Field(default=0, ge=0, description="实际模型调用次数")
    parallel_wall_ms: int = Field(
        default=0, ge=0, description="冲突阶段并行执行的真实墙钟耗时"
    )
