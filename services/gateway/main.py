"""
Gateway — API 网关

认证 (JWT) + 路由转发 + 限流 + 熔断 + Prometheus metrics

端口: 8000
"""
import httpx
import os
import json
import time
from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
import asyncpg
import uvicorn

from common.config import config
from common.auth import (
    create_access_token, decode_token, hash_password, verify_password,
    get_current_user, require_role, is_public_path,
)
from common.resilience import get_breaker, all_breakers_status, check_rate_limit, RateLimiter
from common.metrics import setup_metrics, circuit_breaker_state
from common.errors import setup_error_handlers

app = FastAPI(
    title="NexusAI Gateway",
    description="API 网关 — 认证 / 路由 / 限流 / 熔断",
    version="2.0.0",
)

# ── CORS (whitelist, not *) ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Metrics & Error handling ──
setup_metrics(app, "gateway")
setup_error_handlers(app, "gateway")

# ── Database ──
DATABASE_URL = os.getenv("DATABASE_URL", config.DATABASE_URL)
_pool: asyncpg.Pool | None = None


@app.on_event("startup")
async def startup():
    global _pool
    _pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=2, max_size=5)


@app.on_event("shutdown")
async def shutdown():
    if _pool:
        await _pool.close()


# ═══════════════════════════════════════════════════════════════
#  Authentication
# ═══════════════════════════════════════════════════════════════

class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/v1/auth/login")
async def login(body: LoginRequest, request: Request):
    """用户登录，返回 JWT token"""
    # Rate limit: 10 login attempts per minute per IP
    auth_limiter = RateLimiter(max_requests=10, window_seconds=60.0)
    check_rate_limit(request, auth_limiter)

    async with _pool.acquire() as conn:
        # Use pgcrypto's crypt() to verify password
        row = await conn.fetchrow(
            "SELECT id, username, role, password = crypt($2, password) AS verified FROM users WHERE username = $1",
            body.username,
            body.password,
        )

    if not row or not row["verified"]:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_access_token({
        "sub": row["username"],
        "user_id": row["id"],
        "role": row["role"],
    })

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": row["id"],
            "username": row["username"],
            "role": row["role"],
        },
    }


@app.get("/api/v1/auth/me")
async def get_me(user: dict = Depends(get_current_user)):
    """获取当前用户信息"""
    return user


@app.get("/api/v1/auth/circuit-breakers")
async def get_circuit_breakers(user: dict = Depends(require_role("admin"))):
    """获取熔断器状态（管理员）"""
    return all_breakers_status()


def _update_circuit_breaker_metrics():
    """Update circuit breaker state gauges for Prometheus"""
    state_map = {"closed": 0, "half_open": 1, "open": 2}
    for name, info in all_breakers_status().items():
        state = info.get("state", "closed")
        circuit_breaker_state.set(float(state_map.get(state, 0)), service=name)


# ═══════════════════════════════════════════════════════════════
#  Auth Middleware + Proxy
# ═══════════════════════════════════════════════════════════════

# 服务路由表
ROUTES = {
    "/api/v1/sensors": {"url": "http://iot_collector:8001", "prefix": "/api/v1/sensors"},
    "/api/v1/metrics": {"url": "http://analytics:8005", "prefix": "/api/v1/metrics"},
    "/api/v1/alerts": {"url": "http://alert:8006", "prefix": "/api/v1/alerts"},
    "/api/v1/devices": {"url": "http://asset_manager:8007", "prefix": "/api/v1/devices"},
    "/api/v1/ai": {"url": "http://ai_engine:8004", "prefix": "/api/v1/ai"},
    "/api/v1/simulator": {"url": "http://simulator:8009", "prefix": "/api/v1/simulator"},
    "/api/v1/faults": {"url": "http://simulator:8009", "prefix": "/api/v1/faults"},
    "/api/v1/workorders": {"url": "http://asset_manager:8007", "prefix": "/api/v1/workorders"},
    "/api/v1/users": {"url": "http://asset_manager:8007", "prefix": "/api/v1/users"},
    "/api/v1/audit-logs": {"url": "http://asset_manager:8007", "prefix": "/api/v1/audit-logs"},
}


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "gateway", "version": "2.0.0"}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy(path: str, request: Request):
    """通用代理 — 认证 + 限流 + 熔断 + 转发"""
    full_path = f"/{path}"

    # ── 1. 认证检查 ──
    if not is_public_path(full_path):
        try:
            user = await get_current_user(request)
        except HTTPException:
            raise
        # Rate limit authenticated requests
        check_rate_limit(request)

    # ── 2. 匹配路由 ──
    target = None
    for prefix, route in ROUTES.items():
        if full_path.startswith(prefix):
            target = route
            break

    if not target:
        if full_path.startswith("/api/v1/diagnosis") or full_path.startswith("/api/v1/analytics"):
            target = {"url": "http://analytics:8005", "prefix": ""}
        elif full_path.startswith("/api/v1/observability"):
            target = {"url": "http://observability:8008", "prefix": ""}
        else:
            raise HTTPException(status_code=404, detail=f"无匹配路由: {full_path}")

    # ── 3. 熔断器 ──
    service_name = target["url"].split("//")[1].split(":")[0]
    breaker = get_breaker(service_name, failure_threshold=5, recovery_timeout=30.0)

    # ── 4. 转发请求 (through circuit breaker) ──
    async def _do_proxy():
        body = await request.body()
        # Forward auth headers
        fwd_headers = {
            "Content-Type": request.headers.get("content-type", "application/json"),
            "X-Forwarded-For": request.client.host if request.client else "",
            "X-Forwarded-Path": full_path,
        }
        # Pass through auth token
        auth_header = request.headers.get("Authorization")
        if auth_header:
            fwd_headers["Authorization"] = auth_header

        async with httpx.AsyncClient() as client:
            resp = await client.request(
                method=request.method,
                url=f"{target['url']}{full_path}",
                headers=fwd_headers,
                params=dict(request.query_params),
                content=body if body else None,
                timeout=30.0,
            )
            return resp

    try:
        resp = await breaker.call(_do_proxy)
        _update_circuit_breaker_metrics()
        return StreamingResponse(
            iter([resp.content]),
            status_code=resp.status_code,
            headers=dict(resp.headers),
            media_type=resp.headers.get("content-type"),
        )
    except HTTPException:
        raise
    except httpx.ConnectError:
        _update_circuit_breaker_metrics()
        raise HTTPException(status_code=503, detail=f"服务不可达: {target['url']}")
    except Exception as e:
        _update_circuit_breaker_metrics()
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════
#  WebSocket Proxy (with token auth via query param)
# ═══════════════════════════════════════════════════════════════

@app.websocket("/ws/{channel}")
async def websocket_proxy(websocket: WebSocket, channel: str):
    """WebSocket 代理 — token 通过 query param 传递"""
    # Verify token
    token = websocket.query_params.get("token")
    if token:
        try:
            decode_token(token)
        except Exception:
            await websocket.close(code=4001, reason="Invalid token")
            return

    await websocket.accept()
    target_ws_url = f"ws://analytics:8005/ws/{channel}"

    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(os.getenv("REDIS_URL", "redis://redis:6379"), decode_responses=True)

        channel_map = {
            "sensors": "sensor_data_live",
            "alerts": "alert_triggered",
            "diagnosis": "diagnosis_complete",
            "oee": "oee_update",
            "anomaly": "anomaly_detected",
        }
        redis_channel = channel_map.get(channel, channel)

        pubsub = r.pubsub()
        await pubsub.subscribe(redis_channel)

        try:
            while True:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg and msg["type"] == "message":
                    await websocket.send_text(msg["data"])
        except WebSocketDisconnect:
            pass
        finally:
            await pubsub.unsubscribe(redis_channel)
            await r.close()

    except Exception as e:
        print(f"[Gateway WS] 错误: {e}")
        try:
            await websocket.close()
        except Exception:
            pass


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
