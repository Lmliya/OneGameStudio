"""全局配置：所有可调参数集中在这里，通过环境变量或 .env 覆盖。

模型名称、价格与密钥一律通过配置注入，业务代码中不得出现硬编码。
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # demo：展示预验证历史任务，禁止真实模型调用（默认，适合公开演示）
    # live：调用真实模型，必须配置服务端 API Key、模型名与访问令牌
    app_mode: Literal["demo", "live"] = "demo"
    # demo 模式下是否允许提交新的 Mock 任务；公开部署应设为 true
    demo_read_only: bool = False
    # 历史演示任务的落盘目录（随仓库提交，只读）
    demo_dir: Path = Path("demo/tasks")

    # 为 true 时使用离线 MockProvider，不发起任何真实网络请求
    mock_mode: bool = True

    # Live 模式访问令牌：非空时，创建任务必须携带 X-OGS-Token 请求头
    access_token: str = ""
    # 单 IP 每分钟允许创建的任务数（公开部署建议调低到 6）
    task_rate_limit_per_minute: int = 30
    # 同时运行的活跃任务上限，防止资源耗尽
    max_active_tasks: int = 3
    # Demo 回放事件之间的间隔（毫秒）
    demo_replay_ms: int = 350

    # 真实模式配置（OpenAI 兼容接口）。模型名必须由环境变量指定，避免硬编码过时模型。
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = ""

    # 单次模型调用超时（秒）
    request_timeout_seconds: float = 30.0

    # 目录
    talents_dir: Path = Path("talents")
    output_dir: Path = Path("output")
    # 阶段 8：Talent 版本库、经验、提案与评估报告的落盘目录
    evolution_dir: Path = Path("output/evolution")
    # Harness 4：provider 层有限重试（只对调用异常重试，超时不重试）
    provider_max_retries: int = 1
    provider_retry_backoff_seconds: float = 0.5

    # Harness 5：单任务预算与模型价格表
    budget_usd: float = 1.0
    budget_soft_ratio: float = 0.7
    light_model: str = ""
    max_output_tokens: int = 2048
    # 阶段 9：冲突阶段两名总监的输出上限；只约束顾问意见，不约束游戏代码
    opinion_max_output_tokens: int = 600
    # JSON：{"模型名": {"input_per_1k": 0.0, "output_per_1k": 0.0}}，默认空 = 费用未知
    model_prices: str = ""
    # 并发模型调用上限；预算检查在串行化锁内进行。
    # 默认 2：冲突阶段需要 Creative 与 Delivery 真实并行；最坏超额多一次顾问调用。
    max_concurrent_calls: int = 2

    # 自动修复轮次上限（默认最多两次代码修复）
    max_fix_rounds: int = 2

    # 每个员工的阶段最少展示时长（秒），用于驾驶舱动画节奏；0 表示不等待
    stage_min_seconds: float = 6.0


@lru_cache
def get_settings() -> Settings:
    """进程内单例，避免重复解析 .env。"""
    return Settings()
