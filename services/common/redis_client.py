"""Redis 连接管理"""
import redis.asyncio as redis
import os

_redis: redis.Redis | None = None

async def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379"),
            decode_responses=True,
        )
    return _redis

async def close_redis():
    global _redis
    if _redis:
        await _redis.close()
        _redis = None
