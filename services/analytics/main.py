"""
Analytics API — 分析查询服务

REST API 查询指标（OEE、产量、良率、设备状态）
WebSocket 实时推送（传感器数据、告警、AI 诊断、OEE 更新）
Redis 缓存热点查询

端口: 8005
"""

import json
import asyncio
import os
from datetime import datetime, timezone, timedelta
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as aioredis
import asyncpg
import uvicorn

from common.config import config
from common.metrics import setup_metrics
from common.errors import setup_error_handlers

app = FastAPI(title="NexusAI Analytics API", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
setup_metrics(app, "analytics")
setup_error_handlers(app, "analytics")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://nexusai:nexusai123@localhost:5432/nexusai")

_redis: aioredis.Redis | None = None
_pool: asyncpg.Pool | None = None

# WebSocket 频道映射
WS_CHANNEL_MAP = {
    "sensors": "sensor_data_live",
    "alerts": "alert_triggered",
    "diagnosis": "diagnosis_complete",
    "oee": "oee_update",
    "anomaly": "anomaly_detected",
    "device_status": "device_status",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _redis, _pool
    _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    _pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=2, max_size=10)
    # 启动传感器数据广播任务
    broadcast_task = asyncio.create_task(_sensor_broadcast_loop())
    yield
    broadcast_task.cancel()
    try:
        await broadcast_task
    except asyncio.CancelledError:
        pass
    if _redis:
        await _redis.close()
    if _pool:
        await _pool.close()


app.router.lifespan_context = lifespan


async def _sensor_broadcast_loop():
    """
    消费 Redis Streams sensor_data（消费组 analytics），
    发布到 Pub/Sub sensor_data_live 供 WebSocket 推送
    """
    consumer = f"analytics-{int(datetime.now(timezone.utc).timestamp())}"
    try:
        await _redis.xgroup_create("sensor_data", "analytics", id="0", mkstream=True)
    except aioredis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise

    while True:
        try:
            messages = await _redis.xreadgroup(
                groupname="analytics",
                consumername=consumer,
                streams={"sensor_data": ">"},
                count=50,
                block=2000,
            )
            if not messages:
                continue
            for _stream, msgs in messages:
                for msg_id, fields in msgs:
                    data = fields.get("data") or json.dumps({
                        "device_id": fields.get("device_id"),
                        "timestamp": fields.get("timestamp"),
                        "sensors": json.loads(fields.get("sensors", "{}")),
                        "status": fields.get("status"),
                    })
                    await _redis.publish("sensor_data_live", data)
                    await _redis.xack("sensor_data", "analytics", msg_id)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[Analytics] broadcast error: {e}")
            await asyncio.sleep(1)


# ═══════════════════════════════════════════════════════════════
#  REST API
# ═══════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "analytics"}


@app.get("/api/v1/metrics/oee")
async def get_oee(device_id: Optional[str] = None, hours: int = 1):
    """查询 OEE 指标"""
    if device_id:
        rows = await _pool.fetch(
            """
            SELECT time, device_id, availability, performance, quality, oee, output_count, defect_count
            FROM oee_metrics
            WHERE device_id = $1 AND time > NOW() - ($2 * INTERVAL '1 hour')
            ORDER BY time DESC LIMIT 200
            """,
            device_id,
            hours,
        )
    else:
        rows = await _pool.fetch(
            """
            SELECT time, device_id, availability, performance, quality, oee, output_count, defect_count
            FROM oee_metrics
            WHERE time > NOW() - ($1 * INTERVAL '1 hour')
            ORDER BY time DESC LIMIT 500
            """,
            hours,
        )
    return {
        "count": len(rows),
        "data": [
            {
                "time": r["time"].isoformat() if r["time"] else None,
                "device_id": r["device_id"],
                "availability": r["availability"],
                "performance": r["performance"],
                "quality": r["quality"],
                "oee": r["oee"],
                "output_count": r["output_count"],
                "defect_count": r["defect_count"],
            }
            for r in rows
        ],
    }


@app.get("/api/v1/metrics/oee/latest")
async def get_latest_oee():
    """查询所有设备最新 OEE"""
    rows = await _pool.fetch(
        """
        SELECT DISTINCT ON (device_id)
            time, device_id, availability, performance, quality, oee, output_count, defect_count
        FROM oee_metrics
        ORDER BY device_id, time DESC
        """
    )
    return {
        "data": [
            {
                "time": r["time"].isoformat() if r["time"] else None,
                "device_id": r["device_id"],
                "availability": r["availability"],
                "performance": r["performance"],
                "quality": r["quality"],
                "oee": r["oee"],
                "output_count": r["output_count"],
                "defect_count": r["defect_count"],
            }
            for r in rows
        ]
    }


@app.get("/api/v1/metrics/sensors")
async def get_sensor_readings(
    device_id: str = Query(...),
    sensor_type: Optional[str] = None,
    minutes: int = 10,
):
    """查询传感器历史数据"""
    if sensor_type:
        rows = await _pool.fetch(
            """
            SELECT time, device_id, sensor_type, value, status
            FROM sensor_readings
            WHERE device_id = $1 AND sensor_type = $2
              AND time > NOW() - ($3 * INTERVAL '1 minute')
            ORDER BY time ASC LIMIT 600
            """,
            device_id,
            sensor_type,
            minutes,
        )
    else:
        rows = await _pool.fetch(
            """
            SELECT time, device_id, sensor_type, value, status
            FROM sensor_readings
            WHERE device_id = $1
              AND time > NOW() - ($2 * INTERVAL '1 minute')
            ORDER BY time ASC LIMIT 2000
            """,
            device_id,
            minutes,
        )
    return {
        "count": len(rows),
        "data": [
            {
                "time": r["time"].isoformat() if r["time"] else None,
                "device_id": r["device_id"],
                "sensor_type": r["sensor_type"],
                "value": r["value"],
                "status": r["status"],
            }
            for r in rows
        ],
    }


@app.get("/api/v1/metrics/overview")
async def get_overview():
    """工厂总览数据（缓存 5 秒）"""
    # 尝试从 Redis 缓存读取
    cached = await _redis.get("metrics_overview")
    if cached:
        return json.loads(cached)

    # 查询最新 OEE
    oee_rows = await _pool.fetch(
        """
        SELECT DISTINCT ON (device_id)
            device_id, oee, availability, performance, quality, output_count, defect_count
        FROM oee_metrics
        ORDER BY device_id, time DESC
        """
    )

    # 查询设备状态
    device_rows = await _pool.fetch(
        "SELECT device_id, name, line, type, status FROM devices"
    )

    # 查询最新告警数
    alert_count = await _pool.fetchval(
        "SELECT COUNT(*) FROM alerts WHERE status = 'triggered'"
    )

    # 查询最新诊断
    diag_rows = await _pool.fetch(
        """
        SELECT device_id, anomaly_type, urgency, created_at
        FROM diagnosis_reports
        ORDER BY created_at DESC LIMIT 5
        """
    )

    # 计算总产量和总缺陷
    total_output = sum(r["output_count"] or 0 for r in oee_rows)
    total_defects = sum(r["defect_count"] or 0 for r in oee_rows)
    avg_oee = sum(r["oee"] or 0 for r in oee_rows) / len(oee_rows) if oee_rows else 0

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_devices": len(device_rows),
            "running_devices": sum(1 for r in device_rows if r["status"] == "running"),
            "avg_oee": round(avg_oee, 2),
            "total_output": total_output,
            "total_defects": total_defects,
            "defect_rate": round(total_defects / total_output * 100, 2) if total_output > 0 else 0,
            "active_alerts": alert_count,
        },
        "devices": [
            {
                "device_id": r["device_id"],
                "name": r["name"],
                "line": r["line"],
                "type": r["type"],
                "status": r["status"],
            }
            for r in device_rows
        ],
        "oee_by_device": [
            {
                "device_id": r["device_id"],
                "oee": round(r["oee"], 2) if r["oee"] else 0,
                "availability": round(r["availability"], 2) if r["availability"] else 0,
                "performance": round(r["performance"], 2) if r["performance"] else 0,
                "quality": round(r["quality"], 2) if r["quality"] else 0,
                "output": r["output_count"] or 0,
                "defects": r["defect_count"] or 0,
            }
            for r in oee_rows
        ],
        "recent_diagnoses": [
            {
                "device_id": r["device_id"],
                "anomaly_type": r["anomaly_type"],
                "urgency": r["urgency"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in diag_rows
        ],
    }

    # 缓存 5 秒
    await _redis.set("metrics_overview", json.dumps(result, ensure_ascii=False), ex=5)
    return result


@app.get("/api/v1/metrics/output")
async def get_output_stats(hours: int = 1):
    """产量统计"""
    rows = await _pool.fetch(
        """
        SELECT device_id,
               SUM(output_count) as total_output,
               SUM(defect_count) as total_defects,
               AVG(oee) as avg_oee
        FROM oee_metrics
        WHERE time > NOW() - ($1 * INTERVAL '1 hour')
        GROUP BY device_id
        ORDER BY device_id
        """,
        hours,
    )
    return {
        "hours": hours,
        "data": [
            {
                "device_id": r["device_id"],
                "total_output": r["total_output"] or 0,
                "total_defects": r["total_defects"] or 0,
                "avg_oee": round(r["avg_oee"], 2) if r["avg_oee"] else 0,
            }
            for r in rows
        ],
    }


# ═══════════════════════════════════════════════════════════════
#  WebSocket 实时推送
# ═══════════════════════════════════════════════════════════════

@app.websocket("/ws/{channel}")
async def websocket_endpoint(websocket: WebSocket, channel: str):
    """
    WebSocket 实时推送
    channel: sensors / alerts / diagnosis / oee / anomaly / device_status
    """
    await websocket.accept()

    redis_channel = WS_CHANNEL_MAP.get(channel, channel)
    if not redis_channel:
        await websocket.close(code=4000, reason=f"Unknown channel: {channel}")
        return

    pubsub = _redis.pubsub()
    await pubsub.subscribe(redis_channel)

    try:
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg and msg["type"] == "message":
                await websocket.send_text(msg["data"])
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[Analytics WS] error: {e}")
    finally:
        await pubsub.unsubscribe(redis_channel)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8005)
