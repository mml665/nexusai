"""
Observability — 可观测性服务

服务健康检查、系统状态面板、服务依赖图

端口: 8008
"""

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
import redis.asyncio as aioredis
import asyncpg
import uvicorn

app = FastAPI(title="NexusAI Observability", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://nexusai:nexusai123@postgres:5432/nexusai")
SERVICES_ENV = os.getenv("SERVICES", "gateway:8000,iot_collector:8001,stream_processor:8002,ai_engine:8004,analytics:8005,alert:8006,asset_manager:8007")

# 解析服务列表
SERVICES = []
for svc in SERVICES_ENV.split(","):
    name, _, port = svc.strip().partition(":")
    SERVICES.append({"name": name, "port": int(port), "url": f"http://{name}:{port}"})

# 服务状态缓存
_service_status: dict[str, dict] = {}
# 请求追踪记录（简化版）
_request_traces: list[dict] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动健康检查循环
    health_task = asyncio.create_task(_health_check_loop())
    yield
    health_task.cancel()
    try:
        await health_task
    except asyncio.CancelledError:
        pass


app.router.lifespan_context = lifespan


async def _health_check_loop():
    """每 10 秒检查所有服务健康状态"""
    while True:
        await asyncio.sleep(10)
        await _check_all_services()


async def _check_all_services():
    """检查所有服务"""
    async with httpx.AsyncClient(timeout=5.0) as client:
        for svc in SERVICES:
            name = svc["name"]
            start = time.time()
            try:
                resp = await client.get(f"{svc['url']}/health")
                latency_ms = round((time.time() - start) * 1000, 1)
                _service_status[name] = {
                    "name": name,
                    "port": svc["port"],
                    "status": "healthy" if resp.status_code == 200 else "degraded",
                    "http_status": resp.status_code,
                    "latency_ms": latency_ms,
                    "last_check": datetime.now(timezone.utc).isoformat(),
                    "detail": resp.json() if resp.status_code == 200 else None,
                }
            except Exception as e:
                latency_ms = round((time.time() - start) * 1000, 1)
                _service_status[name] = {
                    "name": name,
                    "port": svc["port"],
                    "status": "down",
                    "http_status": None,
                    "latency_ms": latency_ms,
                    "last_check": datetime.now(timezone.utc).isoformat(),
                    "error": str(e),
                }


# ═══════════════════════════════════════════════════════════════
#  REST API
# ═══════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "observability"}


@app.get("/api/v1/observability/services")
async def list_services():
    """所有服务状态"""
    # 如果没有缓存，立即检查一次
    if not _service_status:
        await _check_all_services()

    services = list(_service_status.values())
    healthy = sum(1 for s in services if s["status"] == "healthy")
    degraded = sum(1 for s in services if s["status"] == "degraded")
    down = sum(1 for s in services if s["status"] == "down")

    return {
        "total": len(services),
        "healthy": healthy,
        "degraded": degraded,
        "down": down,
        "services": services,
    }


@app.get("/api/v1/observability/services/{name}")
async def get_service_detail(name: str):
    """单个服务详情"""
    # 找到服务
    svc = next((s for s in SERVICES if s["name"] == name), None)
    if not svc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"未知服务: {name}")

    # 实时检查
    async with httpx.AsyncClient(timeout=5.0) as client:
        start = time.time()
        try:
            resp = await client.get(f"{svc['url']}/health")
            latency_ms = round((time.time() - start) * 1000, 1)
            return {
                "name": name,
                "port": svc["port"],
                "url": svc["url"],
                "status": "healthy" if resp.status_code == 200 else "degraded",
                "http_status": resp.status_code,
                "latency_ms": latency_ms,
                "last_check": datetime.now(timezone.utc).isoformat(),
                "detail": resp.json(),
            }
        except Exception as e:
            latency_ms = round((time.time() - start) * 1000, 1)
            return {
                "name": name,
                "port": svc["port"],
                "url": svc["url"],
                "status": "down",
                "http_status": None,
                "latency_ms": latency_ms,
                "last_check": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
            }


@app.get("/api/v1/observability/system")
async def system_status():
    """系统总览状态"""
    # 如果没有缓存，立即检查一次
    if not _service_status:
        await _check_all_services()

    services = list(_service_status.values())
    healthy = sum(1 for s in services if s["status"] == "healthy")

    # 检查基础设施
    infra_status = {}
    
    # Redis
    try:
        r = aioredis.from_url(REDIS_URL, decode_responses=True)
        await r.ping()
        info = await r.info()
        infra_status["redis"] = {
            "status": "healthy",
            "version": info.get("redis_version"),
            "used_memory_human": info.get("used_memory_human"),
            "connected_clients": info.get("connected_clients"),
        }
        await r.close()
    except Exception as e:
        infra_status["redis"] = {"status": "down", "error": str(e)}

    # PostgreSQL
    try:
        pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=1, max_size=2)
        async with pool.acquire() as conn:
            pg_version = await conn.fetchval("SELECT version()")
            db_size = await conn.fetchval("SELECT pg_size_pretty(pg_database_size('nexusai'))")
            table_count = await conn.fetchval("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
        await pool.close()
        infra_status["postgres"] = {
            "status": "healthy",
            "version": pg_version,
            "db_size": db_size,
            "table_count": table_count,
        }
    except Exception as e:
        infra_status["postgres"] = {"status": "down", "error": str(e)}

    # 计算系统整体健康度
    total_infra = len(infra_status)
    healthy_infra = sum(1 for v in infra_status.values() if v["status"] == "healthy")
    total_services = len(services)
    healthy_services = healthy

    overall = "healthy" if (healthy_infra == total_infra and healthy_services == total_services) else \
              "degraded" if (healthy_infra > 0 and healthy_services > 0) else "critical"

    return {
        "overall_status": overall,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {
            "total": total_services,
            "healthy": healthy_services,
            "unhealthy": total_services - healthy_services,
        },
        "infrastructure": {
            "total": total_infra,
            "healthy": healthy_infra,
            "details": infra_status,
        },
        "service_list": [
            {"name": s["name"], "status": s["status"], "latency_ms": s.get("latency_ms")}
            for s in services
        ],
    }


@app.get("/api/v1/observability/traces")
async def list_traces(limit: int = 20):
    """请求追踪记录（简化版）"""
    return {
        "count": len(_request_traces[:limit]),
        "data": _request_traces[:limit],
    }


@app.post("/api/v1/observability/traces")
async def add_trace(trace: dict):
    """记录请求追踪"""
    trace["recorded_at"] = datetime.now(timezone.utc).isoformat()
    _request_traces.append(trace)
    # 保留最近 100 条
    if len(_request_traces) > 100:
        _request_traces.pop(0)
    return {"status": "recorded"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8008)
