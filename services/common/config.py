"""共享配置管理"""
import os

class Config:
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://nexusai:nexusai123@localhost:5432/nexusai")
    ES_URL = os.getenv("ES_URL", "http://localhost:9200")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
    PUSH_INTERVAL = float(os.getenv("PUSH_INTERVAL", "1.0"))

config = Config()
