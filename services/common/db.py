"""PostgreSQL / TimescaleDB 连接管理"""
import asyncpg
import os
from typing import Optional

_pool: Optional[asyncpg.Pool] = None

async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=os.getenv("DATABASE_URL", "postgresql://nexusai:nexusai123@localhost:5432/nexusai"),
            min_size=2,
            max_size=10,
        )
    return _pool

async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
