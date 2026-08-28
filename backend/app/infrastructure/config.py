from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://run_coach:run_coach@localhost:5433/run_coach"
    jwt_secret: str = "change-me-in-development"
    jwt_algorithm: str = "HS256"
    jwt_expire_seconds: int = 7 * 24 * 3600

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
