"""自进化的领域异常。"""


class EvolutionError(RuntimeError):
    """自进化流程中的通用错误（非法状态、缺失证据等）。"""


class VersionNotFoundError(EvolutionError):
    """请求的 Talent 版本不存在。"""


class EvolutionStateError(EvolutionError):
    """当前状态不允许该操作（例如未评估就启用）。"""


class ImmutableFieldError(EvolutionError):
    """试图修改安全边界字段（工具白名单、输出契约、模型等）。"""
