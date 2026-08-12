"""
Smart Alert — 告警引擎

订阅 anomaly_detected 事件，执行告警分级、去重、抑制
升级策略：未处理告警自动升级
多渠道通知：WebSocket + 数据库持久化

端口: 8006
"""

import json
import asyncio
import os
import time
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Optional
from dataclasses import dataclass, field

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as aioredis
import asyncpg
import uvicorn

app = FastAPI(title="NexusAI Smart Alert", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://nexusai:nexusai123@localhost:5432/nexusai")

_redis: aioredis.Redis | None = None
_pool: asyncpg.Pool | None = None

CHANNEL_ANOMALY = "anomaly_detected"
CHANNEL_ALERT = "alert_triggered"

# 去重窗口：同一设备+传感器+类型 30 秒内只告警一次
DEDUP_WINDOW = 30.0
# 升级间隔：warning 告警 5 分钟未确认升级为 critical
ESCALATION_INTERVAL = 300


@dataclass
class AlertDedup:
    """告警去重状态"""
    key: str
    last_time: float
    count: int = 1


# 设备+传感器+异常类型 → 最后告警时间
_dedup_map: dict[str, AlertDedup] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _redis, _pool
    _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    _pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=2, max_size=10)

    # 启动告警订阅和升级检查
    alert_task = asyncio.create_task(_alert_subscriber_loop())
    escalation_task = asyncio.create_task(_escalation_loop())

    yield

    alert_task.cancel()
    escalation_task.cancel()
    for t in (alert_task, escalation_task):
        try:
            await t
        except asyncio.CancelledError:
            pass
    if _redis:
        await _redis.close()
    if _pool:
        await _pool.close()


app.router.lifespan_context = lifespan


async def _alert_subscriber_loop():
    """订阅 anomaly_detected，生成告警"""
    pubsub = _redis.pubsub()
    await pubsub.subscribe(CHANNEL_ANOMALY)
    print("[Alert] Subscriber started on 'anomaly_detected'")

    while True:
        try:
            msg = await pubsub.get_message(timeout=1.0)
            if msg and msg["type"] == "message":
                await _process_anomaly(msg["data"])
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[Alert] subscriber error: {e}")
            await asyncio.sleep(1)

    await pubsub.unsubscribe(CHANNEL_ANOMALY)


async def _process_anomaly(raw_data: str):
    """处理异常事件，生成告警"""
    try:
        anomaly = json.loads(raw_data)
    except json.JSONDecodeError:
        return

    device_id = anomaly.get("device_id", "")
    sensor_type = anomaly.get("sensor_type", "")
    anomaly_type = anomaly.get("anomaly_type", "")
    severity = anomaly.get("severity", "warning")
    message = anomaly.get("message", "")
    timestamp = anomaly.get("timestamp", datetime.now(timezone.utc).isoformat())

    # ── 去重检查 ──
    dedup_key = f"{device_id}:{sensor_type}:{anomaly_type}"
    now = time.time()
    if dedup_key in _dedup_map:
        entry = _dedup_map[dedup_key]
        if now - entry.last_time < DEDUP_WINDOW:
            entry.count += 1
            entry.last_time = now
            print(f"[Alert] Dedup: {dedup_key} suppressed (count={entry.count})")
            return
        else:
            entry.count = 1
            entry.last_time = now
    else:
        _dedup_map[dedup_key] = AlertDedup(key=dedup_key, last_time=now)

    # ── 确定告警类型 ──
    alert_type = "fault"
    if sensor_type in ("temperature",):
        alert_type = "safety"
    elif anomaly_type == "trend":
        alert_type = "quality"

    # ── 告警标题 ──
    title = f"[{severity.upper()}] {device_id} {sensor_type} 异常"
    description = message

    # ── 写入数据库 ──
    alert_id = await _pool.fetchval(
        """
        INSERT INTO alerts (device_id, type, severity, title, description)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """,
        device_id,
        alert_type,
        severity,
        title,
        description,
    )

    # ── 发布告警事件 ──
    alert_payload = {
        "id": alert_id,
        "device_id": device_id,
        "type": alert_type,
        "severity": severity,
        "title": title,
        "description": description,
        "timestamp": timestamp,
        "anomaly_type": anomaly_type,
        "sensor_type": sensor_type,
        "sensor_data": anomaly.get("sensor_data", {}),
        "context": anomaly.get("context", {}),
    }
    await _redis.publish(CHANNEL_ALERT, json.dumps(alert_payload, ensure_ascii=False))
    print(f"[Alert] #{alert_id} created: {title}")


async def _escalation_loop():
    """定时检查未确认告警，执行升级策略"""
    while True:
        try:
            await asyncio.sleep(60)
            # 查询 5 分钟前触发的 warning 告警，升级为 critical
            escalated = await _pool.fetch(
                """
                UPDATE alerts
                SET severity = 'critical',
                    title = '[ESCALATED] ' || title
                WHERE status = 'triggered'
                  AND severity = 'warning'
                  AND created_at < NOW() - INTERVAL '%s seconds'
                RETURNING id, device_id, title
                """ % ESCALATION_INTERVAL,
            )
            for row in escalated:
                escalation_payload = {
                    "id": row["id"],
                    "device_id": row["device_id"],
                    "type": "escalation",
                    "severity": "critical",
                    "title": row["title"],
                    "description": "告警升级：5分钟内未确认",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                await _redis.publish(CHANNEL_ALERT, json.dumps(escalation_payload, ensure_ascii=False))
                print(f"[Alert] Escalated: #{row['id']} {row['device_id']}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[Alert] escalation error: {e}")


# ═══════════════════════════════════════════════════════════════
#  REST API
# ═══════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "alert"}


@app.get("/api/v1/alerts")
async def list_alerts(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    device_id: Optional[str] = None,
    limit: int = 50,
):
    """查询告警列表"""
    query = "SELECT id, device_id, type, severity, title, description, status, created_at, resolved_at FROM alerts WHERE 1=1"
    params = []
    idx = 1

    if status:
        query += f" AND status = ${idx}"
        params.append(status)
        idx += 1
    if severity:
        query += f" AND severity = ${idx}"
        params.append(severity)
        idx += 1
    if device_id:
        query += f" AND device_id = ${idx}"
        params.append(device_id)
        idx += 1

    query += f" ORDER BY created_at DESC LIMIT ${idx}"
    params.append(limit)

    rows = await _pool.fetch(query, *params)
    return {
        "count": len(rows),
        "data": [
            {
                "id": r["id"],
                "device_id": r["device_id"],
                "type": r["type"],
                "severity": r["severity"],
                "title": r["title"],
                "description": r["description"],
                "status": r["status"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "resolved_at": r["resolved_at"].isoformat() if r["resolved_at"] else None,
            }
            for r in rows
        ],
    }


@app.get("/api/v1/alerts/stats")
async def alert_stats():
    """告警统计"""
    rows = await _pool.fetch(
        """
        SELECT
            severity,
            status,
            COUNT(*) as count
        FROM alerts
        WHERE created_at > NOW() - INTERVAL '24 hours'
        GROUP BY severity, status
        """
    )
    stats = {}
    for r in rows:
        key = f"{r['severity']}_{r['status']}"
        stats[key] = r["count"]

    total = await _pool.fetchval("SELECT COUNT(*) FROM alerts WHERE status = 'triggered'")
    return {
        "active_count": total,
        "by_severity_status": stats,
    }


@app.put("/api/v1/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: int):
    """确认告警"""
    result = await _pool.execute(
        "UPDATE alerts SET status = 'acknowledged' WHERE id = $1 AND status = 'triggered'",
        alert_id,
    )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="告警不存在或已处理")
    return {"id": alert_id, "status": "acknowledged"}


@app.put("/api/v1/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: int):
    """解决告警"""
    result = await _pool.execute(
        "UPDATE alerts SET status = 'resolved', resolved_at = NOW() WHERE id = $1 AND status != 'resolved'",
        alert_id,
    )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="告警不存在或已解决")
    return {"id": alert_id, "status": "resolved"}


@app.put("/api/v1/alerts/{alert_id}/false-alarm")
async def mark_false_alarm(alert_id: int):
    """标记误报"""
    result = await _pool.execute(
        "UPDATE alerts SET status = 'false_alarm', resolved_at = NOW() WHERE id = $1",
        alert_id,
    )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="告警不存在")
    return {"id": alert_id, "status": "false_alarm"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8006)
