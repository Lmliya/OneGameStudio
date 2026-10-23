"""全局配置：所有可调参数集中在这里，通过环境变量或 .env 覆盖。

模型名称与密钥一律通过配置注入，业务代码中不得出现硬编码。
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # 为 true 时使用离线 MockProvider，不发起任何真实网络请求
    mock_mode: bool = True

    # 真实模式配置（OpenAI 兼容接口）
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"

    # 单次模型调用超时（秒）
    request_timeout_seconds: float = 30.0

    # 目录
    talents_dir: Path = Path("talents")
    output_dir: Path = Path("output")

    # 成本预算与自动修复轮次上限
    budget_usd: float = 1.0
    max_fix_rounds: int = 2


@lru_cache
def get_settings() -> Settings:
    """进程内单例，避免重复解析 .env。"""
    return Settings()
