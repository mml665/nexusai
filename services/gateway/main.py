"""Gateway - API 网关
认证、路由转发、限流
"""
import httpx
import os
from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import json

app = FastAPI(title="NexusAI Gateway", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

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
}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy(path: str, request: Request):
    """通用代理 - 转发到对应微服务"""
    full_path = f"/{path}"

    # 匹配路由
    target = None
    for prefix, route in ROUTES.items():
        if full_path.startswith(prefix):
            target = route
            break

    if not target:
        # 尝试 analytics 的其他路由
        if full_path.startswith("/api/v1/diagnosis") or full_path.startswith("/api/v1/analytics"):
            target = {"url": "http://analytics:8005", "prefix": ""}
        else:
            raise HTTPException(status_code=404, detail=f"无匹配路由: {full_path}")

    # 构建目标 URL
    target_url = f"{target['url']}{full_path}"

    # 转发请求
    async with httpx.AsyncClient() as client:
        try:
            body = await request.body()
            resp = await client.request(
                method=request.method,
                url=target_url,
                headers=dict(request.headers),
                params=dict(request.query_params),
                content=body if body else None,
                timeout=30.0,
            )
            return StreamingResponse(
                iter([resp.content]),
                status_code=resp.status_code,
                headers=dict(resp.headers),
                media_type=resp.headers.get("content-type"),
            )
        except httpx.ConnectError:
            raise HTTPException(status_code=503, detail=f"服务不可达: {target['url']}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws/{channel}")
async def websocket_proxy(websocket: WebSocket, channel: str):
    """WebSocket 代理 - 转发到 Analytics 服务"""
    await websocket.accept()
    target_ws_url = f"ws://analytics:8005/ws/{channel}"

    try:
        async with httpx.AsyncClient() as client:
            # 使用 Redis Pub/Sub 代替直接 WebSocket 转发
            import redis.asyncio as aioredis
            r = aioredis.from_url(os.getenv("REDIS_URL", "redis://redis:6379"), decode_responses=True)

            # 频道映射
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


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "gateway"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
