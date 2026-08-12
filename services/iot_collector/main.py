"""IoT Collector - 数据接入服务
接收模拟器推送的传感器数据，校验后写入 Redis Streams
"""
import json
import asyncio
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any
import redis.asyncio as aioredis
import os

from common.config import config
from common.metrics import setup_metrics
from common.errors import setup_error_handlers

app = FastAPI(title="NexusAI IoT Collector", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
setup_metrics(app, "iot_collector")
setup_error_handlers(app, "iot_collector")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
_redis: aioredis.Redis | None = None

STREAM_SENSOR_DATA = "sensor_data"
CHANNEL_DEVICE_STATUS = "device_status"


class SensorReading(BaseModel):
    device_id: str
    timestamp: str
    sensors: Dict[str, float]
    status: str = "running"


@app.on_event("startup")
async def startup():
    global _redis
    _redis = aioredis.from_url(REDIS_URL, decode_responses=True)


@app.on_event("shutdown")
async def shutdown():
    if _redis:
        await _redis.close()


def validate_reading(reading: SensorReading) -> bool:
    if not reading.device_id:
        return False
    if not reading.sensors:
        return False
    if not reading.timestamp:
        return False
    for k, v in reading.sensors.items():
        if v is None or isinstance(v, bool):
            return False
    return True


@app.post("/api/v1/sensors/data")
async def receive_sensor_data(reading: SensorReading):
    if not validate_reading(reading):
        raise HTTPException(status_code=422, detail="无效的传感器数据")

    # 写入 Redis Stream 供 Stream Processor 消费
    stream_data = {
        "device_id": reading.device_id,
        "timestamp": reading.timestamp,
        "sensors": json.dumps(reading.sensors),
        "status": reading.status,
    }
    await _redis.xadd(STREAM_SENSOR_DATA, stream_data)

    # 如果设备状态变化，发布通知
    if reading.status != "running":
        await _redis.publish(CHANNEL_DEVICE_STATUS, json.dumps({
            "device_id": reading.device_id,
            "status": reading.status,
            "timestamp": reading.timestamp,
        }))

    return {"status": "ok", "device_id": reading.device_id}


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "iot_collector"}


@app.get("/api/v1/sensors/stream/info")
async def stream_info():
    length = await _redis.xlen(STREAM_SENSOR_DATA)
    return {"stream": STREAM_SENSOR_DATA, "length": length}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
