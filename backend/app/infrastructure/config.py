"""应用配置：从环境变量与 .env 读取，集中管理全部可调参数。"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """运行配置。敏感项（数据库地址、JWT 密钥、LLM Key）全部来自环境。"""

    database_url: str = "postgresql+asyncpg://run_coach:run_coach@localhost:5433/run_coach"
    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    # JWT 有效期：默认 7 天。
    jwt_expire_seconds: int = 7 * 24 * 3600

    # LLM 三项配置齐备才会启用 LLMReasoner，否则装配时报错。
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None

    # 仅作为 Runtime 护栏，防止无限循环；不是“最多思考几轮”的产品契约。
    agent_max_steps: int = 16
    conversation_history_limit: int = 20

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )
