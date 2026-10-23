"""全局配置：所有可调参数集中在这里，通过环境变量或 .env 覆盖。"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # 为 true 时使用离线 MockLLM，不发起任何真实网络请求
    mock_mode: bool = True

    # 真实模式下的 OpenAI 兼容接口配置
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    default_model: str = "gpt-4o-mini"

    # 任务产物根目录（每个任务一个独立子目录）
    data_dir: Path = Path("data")

    # 成本预算与自动修复轮次上限
    budget_usd: float = 1.0
    max_fix_rounds: int = 2


@lru_cache
def get_settings() -> Settings:
    """进程内单例，避免重复解析 .env。"""
    return Settings()
