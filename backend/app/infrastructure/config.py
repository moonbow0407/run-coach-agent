"""应用配置：从环境变量与 .env 读取，集中管理全部可调参数。"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """运行配置。敏感项（数据库地址、JWT 密钥、LLM Key）全部来自环境。"""

    # 连接串含数据库凭据，不允许有默认值，必须由环境变量或 .env 提供
    database_url: str
    redis_url: str = "redis://localhost:6379/0"  # Redis 地址：事件发件箱投递与 arq 任务队列所在
    worker_queue_name: str = "arq:queue"  # arq 后台任务队列名
    jwt_secret: str = Field(min_length=32)  # JWT 签名密钥（HMAC），至少 32 字符
    jwt_algorithm: str = "HS256"  # JWT 签名算法
    # JWT 有效期：默认 7 天。
    jwt_expire_seconds: int = 7 * 24 * 3600

    # LLM 三项配置齐备才会启用 LLMReasoner，否则装配时报错。
    llm_api_key: str | None = None  # LLM 服务 API Key
    llm_base_url: str | None = None  # LLM 服务地址（兼容 OpenAI 协议）
    llm_model: str | None = None  # 模型名（如 gpt-4o-mini）

    # Memory projector 与 embedding 分开版本化；维度是 Phase 4 持久化合同。
    memory_projector_version: str = "phase4.v1"  # 记忆投影器版本，变更会触发重投影
    memory_embedding_model: str = "text-embedding-3-small"  # 记忆向量的 embedding 模型
    memory_embedding_version: str = "1"  # embedding 产物版本，与模型分开演进
    memory_embedding_dimensions: int = 1536  # 向量维度，须与 pgvector 列一致

    # 仅作为 Runtime 护栏，防止无限循环；不是“最多思考几轮”的产品契约。
    agent_max_steps: int = 16  # 单次 Run 的最大推理步数上限
    conversation_history_limit: int = 20  # 组装 Prompt 时携带的历史消息条数上限

    # Scenario Lab：演示/联调用可推进业务时钟与假数据，仅本地开启；
    # 生产必须保持 False——开启后 API 与 worker 共享 Redis 里的虚拟"现在"。
    enable_scenario_lab: bool = False

    model_config = SettingsConfigDict(  # pydantic-settings 配置：从 .env 读入并忽略未声明变量
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )
