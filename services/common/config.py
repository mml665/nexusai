"""共享配置管理"""
import os


class Config:
    # Infrastructure
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://nexusai:nexusai123@localhost:5432/nexusai")
    ES_URL = os.getenv("ES_URL", "http://localhost:9200")

    # LLM
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

    # Simulator
    PUSH_INTERVAL = float(os.getenv("PUSH_INTERVAL", "1.0"))

    # Auth
    JWT_SECRET = os.getenv("JWT_SECRET", "nexusai-dev-secret-change-in-production")
    JWT_ALGORITHM = "HS256"
    JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))  # 24h

    # CORS
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:80,http://localhost:5173").split(",")


config = Config()
