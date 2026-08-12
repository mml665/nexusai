"""
AI Engine — 智能工厂 AI 引擎主服务

3 个 Agent 协同工作：
1. 异常检测 Agent: 实时消费 Redis Streams，规则+统计检测，<100ms 延迟
2. 预测维护 Agent: 每5分钟定时执行，线性回归趋势分析 + RUL 预测
3. 根因分析 Agent: 异常事件触发，RAG 混合检索 + LLM 生成诊断报告

端口: 8004
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as redis
import uvicorn

from common.config import config
from common.db import get_pool, close_pool
from common.redis_client import get_redis, close_redis
from common.events import (
    STREAM_SENSOR_DATA,
    CHANNEL_ANOMALY,
    CHANNEL_DIAGNOSIS,
    CHANNEL_DEVICE_STATUS,
)

from ai_engine.agents.anomaly import AnomalyDetector, AnomalyEvent
from ai_engine.agents.maintenance import run_maintenance_analysis, MaintenanceResult
from ai_engine.agents.diagnosis import run_diagnosis, DiagnosisResult, init_knowledge_base_embeddings

# ── 日志配置 ──────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("ai_engine")

# ── 全局状态 ──────────────────────────────────────
detector = AnomalyDetector()
app_state: dict = {
    "stream_task": None,
    "diagnosis_task": None,
    "maintenance_task": None,
    "running": False,
    "stats": {
        "total_processed": 0,
        "total_anomalies": 0,
        "total_diagnoses": 0,
        "total_maintenance": 0,
        "last_anomaly": None,
        "last_diagnosis": None,
    },
}

# 诊断去重：同一设备 60 秒内只诊断一次
_last_diagnosis_time: dict[str, float] = {}
DIAGNOSIS_COOLDOWN = 60.0  # seconds


# ── 生命周期管理 ──────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("AI Engine starting up...")
    pool = await get_pool()
    redis_client = await get_redis()

    # 为知识库预生成 embedding（RAG 向量检索需要）
    try:
        kb_count = await init_knowledge_base_embeddings(pool)
        logger.info(f"Knowledge base embeddings initialized: {kb_count} rows")
    except Exception as e:
        logger.warning(f"Failed to initialize knowledge base embeddings: {e}")

    # 确保 consumer group 存在
    try:
        await redis_client.xgroup_create(STREAM_SENSOR_DATA, "ai_engine", id="0", mkstream=True)
        logger.info("Consumer group 'ai_engine' created")
    except redis.ResponseError as e:
        if "BUSYGROUP" in str(e):
            logger.info("Consumer group 'ai_engine' already exists")
        else:
            raise

    app_state["running"] = True

    # 启动后台任务
    app_state["stream_task"] = asyncio.create_task(_stream_consumer_loop())
    app_state["diagnosis_task"] = asyncio.create_task(_diagnosis_subscriber_loop())
    app_state["maintenance_task"] = asyncio.create_task(_maintenance_scheduler_loop())

    logger.info("AI Engine started: 3 agents active")
    yield

    # 优雅关闭
    app_state["running"] = False
    for task_key in ("stream_task", "diagnosis_task", "maintenance_task"):
        task = app_state[task_key]
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    await close_pool()
    await close_redis()
    logger.info("AI Engine shut down")


app = FastAPI(
    title="NexusAI AI Engine",
    description="智能工厂 AI 引擎 — 异常检测 / 预测维护 / 根因分析",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════════════
#  Agent 1: 异常检测 — 消费 Redis Streams
# ═══════════════════════════════════════════════════════════════════

async def _stream_consumer_loop():
    """
    持续消费 Redis Streams sensor_data，执行实时异常检测

    消费组: ai_engine
    消费者: ai_engine-{timestamp}
    """
    redis_client = await get_redis()
    consumer_name = f"ai_engine-{int(datetime.now(timezone.utc).timestamp())}"
    logger.info(f"Stream consumer started: {consumer_name}")

    while app_state["running"]:
        try:
            # XREADGROUP 阻塞读取，最多等 5 秒
            messages = await redis_client.xreadgroup(
                groupname="ai_engine",
                consumername=consumer_name,
                streams={STREAM_SENSOR_DATA: ">"},
                count=50,
                block=5000,
            )

            if not messages:
                continue

            for _stream, msgs in messages:
                for msg_id, fields in msgs:
                    try:
                        reading = {
                            "device_id": fields.get("device_id", ""),
                            "timestamp": fields.get("timestamp", ""),
                            "sensors": json.loads(fields.get("sensors", "{}")),
                            "status": fields.get("status", "running"),
                        }
                        events = detector.check(reading)
                        app_state["stats"]["total_processed"] += 1

                        if events:
                            app_state["stats"]["total_anomalies"] += len(events)
                            await _publish_anomalies(reading, events)

                        # ACK
                        await redis_client.xack(STREAM_SENSOR_DATA, "ai_engine", msg_id)
                    except Exception as e:
                        logger.error(f"Error processing message {msg_id}: {e}")
                        await redis_client.xack(STREAM_SENSOR_DATA, "ai_engine", msg_id)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Stream consumer error: {e}")
            await asyncio.sleep(1)


async def _publish_anomalies(reading: dict, events: list[AnomalyEvent]):
    """发布异常事件到 Pub/Sub"""
    redis_client = await get_redis()
    device_id = reading["device_id"]
    timestamp = reading.get("timestamp", datetime.now(timezone.utc).isoformat())

    # 按 severity 排序，最严重的先发
    events_sorted = sorted(events, key=lambda e: 0 if e.severity == "critical" else 1)

    for ev in events_sorted:
        payload = {
            "device_id": ev.device_id,
            "sensor_type": ev.sensor_type,
            "value": ev.value,
            "anomaly_type": ev.anomaly_type,
            "severity": ev.severity,
            "message": ev.message,
            "timestamp": timestamp,
            "context": ev.context,
            "sensor_data": reading.get("sensors", {}),
        }
        await redis_client.publish(CHANNEL_ANOMALY, json.dumps(payload, ensure_ascii=False))
        logger.info(f"Anomaly detected: {ev.message}")

    app_state["stats"]["last_anomaly"] = {
        "device_id": device_id,
        "timestamp": timestamp,
        "count": len(events),
        "top_severity": events_sorted[0].severity,
    }


# ═══════════════════════════════════════════════════════════════════
#  Agent 3: 根因分析 — 订阅异常事件触发诊断
# ═══════════════════════════════════════════════════════════════════

async def _diagnosis_subscriber_loop():
    """
    订阅 Redis Pub/Sub anomaly_detected 频道
    收到异常事件后触发 RAG + LLM 根因分析
    """
    redis_client = await get_redis()
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(CHANNEL_ANOMALY)
    logger.info("Diagnosis subscriber started, listening on 'anomaly_detected'")

    while app_state["running"]:
        try:
            message = await pubsub.get_message(timeout=1.0)
            if message and message["type"] == "message":
                await _handle_anomaly_for_diagnosis(message["data"])
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Diagnosis subscriber error: {e}")
            await asyncio.sleep(1)

    await pubsub.unsubscribe(CHANNEL_ANOMALY)


async def _handle_anomaly_for_diagnosis(raw_data: str):
    """处理单个异常事件，执行诊断"""
    try:
        anomaly = json.loads(raw_data)
    except json.JSONDecodeError:
        return

    device_id = anomaly.get("device_id", "")
    severity = anomaly.get("severity", "warning")

    # 低级告警不触发 LLM 诊断（节省 API 调用）
    if severity == "info":
        return

    # 去重：同一设备 60 秒内只诊断一次
    now = datetime.now(timezone.utc).timestamp()
    last_time = _last_diagnosis_time.get(device_id, 0)
    if now - last_time < DIAGNOSIS_COOLDOWN:
        logger.debug(f"Diagnosis cooldown for {device_id}, skipping")
        return
    _last_diagnosis_time[device_id] = now

    # 收集同一设备最近的异常事件（简单做法：直接用当前事件）
    anomaly_events = [{
        "sensor_type": anomaly.get("sensor_type"),
        "anomaly_type": anomaly.get("anomaly_type"),
        "severity": severity,
        "message": anomaly.get("message", ""),
    }]

    sensor_data = anomaly.get("sensor_data", {})
    if not sensor_data:
        sensor_data = {anomaly.get("sensor_type"): anomaly.get("value")}

    logger.info(f"Triggering diagnosis for {device_id} ({severity})")

    try:
        pool = await get_pool()
        result = await run_diagnosis(pool, device_id, anomaly_events, sensor_data)
        app_state["stats"]["total_diagnoses"] += 1
        app_state["stats"]["last_diagnosis"] = {
            "device_id": device_id,
            "urgency": result.urgency,
            "llm_used": result.llm_used,
            "timestamp": result.created_at,
        }

        # 发布诊断完成事件
        redis_client = await get_redis()
        diagnosis_payload = {
            "device_id": result.device_id,
            "anomaly_type": result.anomaly_type,
            "diagnosis": result.diagnosis,
            "recommendation": result.recommendation,
            "urgency": result.urgency,
            "rag_sources": result.rag_sources,
            "llm_used": result.llm_used,
            "sensor_data": result.sensor_data,
            "timestamp": result.created_at,
        }
        await redis_client.publish(CHANNEL_DIAGNOSIS, json.dumps(diagnosis_payload, ensure_ascii=False))
        logger.info(f"Diagnosis complete for {device_id}: urgency={result.urgency}, llm={result.llm_used}")

    except Exception as e:
        logger.error(f"Diagnosis failed for {device_id}: {e}")


# ═══════════════════════════════════════════════════════════════════
#  Agent 2: 预测维护 — 定时调度
# ═══════════════════════════════════════════════════════════════════

MAINTENANCE_INTERVAL = 300  # 5 分钟

# 全部设备列表
ALL_DEVICES = [
    "CNC-A01", "CNC-A02", "ROBOT-A01",
    "PRESS-B01", "PRESS-B02", "CONV-B01",
    "OVEN-C01", "COOLER-C01", "ROBOT-C01",
]


async def _maintenance_scheduler_loop():
    """每5分钟对所有设备执行预测性维护分析"""
    logger.info(f"Maintenance scheduler started, interval={MAINTENANCE_INTERVAL}s")

    # 启动后等 30 秒让数据积累
    await asyncio.sleep(30)

    while app_state["running"]:
        try:
            pool = await get_pool()
            results: list[MaintenanceResult] = []

            for device_id in ALL_DEVICES:
                try:
                    result = await run_maintenance_analysis(pool, device_id, lookback_hours=2)
                    results.append(result)
                    if result.risk_level in ("high", "critical"):
                        logger.warning(
                            f"Maintenance alert: {device_id} score={result.health_score} "
                            f"risk={result.risk_level} rul={result.predicted_rul}"
                        )
                except Exception as e:
                    logger.error(f"Maintenance analysis failed for {device_id}: {e}")

            app_state["stats"]["total_maintenance"] += 1

            # 发布维护预测摘要
            if results:
                redis_client = await get_redis()
                summary = {
                    "type": "maintenance_update",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "devices": [
                        {
                            "device_id": r.device_id,
                            "health_score": r.health_score,
                            "predicted_rul": r.predicted_rul,
                            "risk_level": r.risk_level,
                            "recommendation": r.recommendation,
                        }
                        for r in results
                    ],
                }
                await redis_client.publish(CHANNEL_DEVICE_STATUS, json.dumps(summary, ensure_ascii=False))
                logger.info(f"Maintenance cycle complete: {len(results)} devices analyzed")

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Maintenance scheduler error: {e}")

        # 等待下一轮
        await asyncio.sleep(MAINTENANCE_INTERVAL)


# ═══════════════════════════════════════════════════════════════════
#  REST API
# ═══════════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "ai_engine",
        "agents": {
            "anomaly_detection": "active",
            "predictive_maintenance": "active",
            "root_cause_analysis": "active",
        },
        "stats": app_state["stats"],
    }


@app.get("/api/v1/ai/stats")
async def get_stats():
    """AI Engine 运行统计"""
    return app_state["stats"]


@app.get("/api/v1/ai/baseline/{device_id}")
async def get_baseline(device_id: str):
    """获取设备传感器基线状态"""
    return {
        "device_id": device_id,
        "baselines": detector.get_device_health_summary(device_id),
    }


@app.post("/api/v1/ai/maintenance/{device_id}")
async def trigger_maintenance(device_id: str):
    """手动触发指定设备的预测维护分析"""
    if device_id not in ALL_DEVICES:
        raise HTTPException(status_code=404, detail=f"Unknown device: {device_id}")

    pool = await get_pool()
    result = await run_maintenance_analysis(pool, device_id, lookback_hours=2)
    return {
        "device_id": result.device_id,
        "health_score": result.health_score,
        "predicted_rul": result.predicted_rul,
        "risk_level": result.risk_level,
        "recommendation": result.recommendation,
        "trends": result.trends,
        "analyzed_at": result.analyzed_at,
    }


@app.post("/api/v1/ai/maintenance")
async def trigger_maintenance_all():
    """手动触发全部设备的预测维护分析"""
    pool = await get_pool()
    results = []
    for device_id in ALL_DEVICES:
        try:
            result = await run_maintenance_analysis(pool, device_id, lookback_hours=2)
            results.append({
                "device_id": result.device_id,
                "health_score": result.health_score,
                "predicted_rul": result.predicted_rul,
                "risk_level": result.risk_level,
                "recommendation": result.recommendation,
                "trends": result.trends,
            })
        except Exception as e:
            results.append({"device_id": device_id, "error": str(e)})
    return {"results": results, "total": len(results)}


@app.post("/api/v1/ai/diagnosis/{device_id}")
async def trigger_diagnosis(device_id: str, body: Optional[dict] = None):
    """
    手动触发指定设备的根因分析

    Body (optional):
    {
        "sensor_data": {"temperature": 85.2, "vibration": 0.7, ...},
        "anomaly_events": [{"sensor_type": "temperature", "anomaly_type": "threshold", ...}]
    }
    """
    if device_id not in ALL_DEVICES:
        raise HTTPException(status_code=404, detail=f"Unknown device: {device_id}")

    body = body or {}
    sensor_data = body.get("sensor_data", {})
    anomaly_events = body.get("anomaly_events", [{
        "sensor_type": "manual",
        "anomaly_type": "manual",
        "severity": "warning",
        "message": f"手动触发诊断: {device_id}",
    }])

    pool = await get_pool()
    result = await run_diagnosis(pool, device_id, anomaly_events, sensor_data)

    # 发布诊断完成事件
    redis_client = await get_redis()
    diagnosis_payload = {
        "device_id": result.device_id,
        "anomaly_type": result.anomaly_type,
        "diagnosis": result.diagnosis,
        "recommendation": result.recommendation,
        "urgency": result.urgency,
        "rag_sources": result.rag_sources,
        "llm_used": result.llm_used,
        "sensor_data": result.sensor_data,
        "timestamp": result.created_at,
    }
    await redis_client.publish(CHANNEL_DIAGNOSIS, json.dumps(diagnosis_payload, ensure_ascii=False))

    return {
        "device_id": result.device_id,
        "anomaly_type": result.anomaly_type,
        "diagnosis": result.diagnosis,
        "recommendation": result.recommendation,
        "urgency": result.urgency,
        "rag_sources": result.rag_sources,
        "llm_used": result.llm_used,
        "sensor_data": result.sensor_data,
        "created_at": result.created_at,
    }


@app.get("/api/v1/ai/diagnoses")
async def list_diagnoses(limit: int = 20):
    """查询最近的诊断报告"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, device_id, anomaly_type, sensor_data, diagnosis,
                   recommendation, urgency, rag_sources, created_at
            FROM diagnosis_reports
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
    def _parse_json(val):
        """数据库中 sensor_data/rag_sources 以 JSON 字符串存储，返回时需解析"""
        if val is None:
            return None
        if isinstance(val, (dict, list)):
            return val
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return val

    return [
        {
            "id": row["id"],
            "device_id": row["device_id"],
            "anomaly_type": row["anomaly_type"],
            "sensor_data": _parse_json(row["sensor_data"]),
            "diagnosis": row["diagnosis"],
            "recommendation": row["recommendation"],
            "urgency": row["urgency"],
            "rag_sources": _parse_json(row["rag_sources"]) or [],
            "llm_used": False,
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "timestamp": row["created_at"].isoformat() if row["created_at"] else None,
        }
        for row in rows
    ]


@app.get("/api/v1/ai/maintenance/history/{device_id}")
async def maintenance_history(device_id: str, limit: int = 20):
    """查询设备维护预测历史"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, device_id, health_score, predicted_rul, risk_level,
                   recommendation, created_at
            FROM maintenance_predictions
            WHERE device_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            device_id,
            limit,
        )
    return [
        {
            "id": row["id"],
            "device_id": row["device_id"],
            "health_score": row["health_score"],
            "predicted_rul": row["predicted_rul"],
            "risk_level": row["risk_level"],
            "recommendation": row["recommendation"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }
        for row in rows
    ]


# ── 入口 ──────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "ai_engine.main:app",
        host="0.0.0.0",
        port=8004,
        reload=True,
        log_level="info",
    )
