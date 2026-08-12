"""Stream Processor - 流处理引擎
从 Redis Streams 消费传感器数据，计算实时 OEE，写入 TimescaleDB
"""
import json
import asyncio
import os
from datetime import datetime, timezone
from collections import defaultdict
import asyncpg
import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="NexusAI Stream Processor", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://nexusai:nexusai123@localhost:5432/nexusai")

STREAM_SENSOR_DATA = "sensor_data"
CHANNEL_OEE_UPDATE = "oee_update"
CONSUMER_GROUP = "stream_processor"

_redis: aioredis.Redis | None = None
_pool: asyncpg.Pool | None = None

# 设备运行状态追踪
device_runtime: dict = {}  # {device_id: {"start_time": ts, "running_secs": 0, "output": 0, "defects": 0}}
# 滑动窗口数据
window_data: dict = defaultdict(lambda: defaultdict(list))  # {device_id: {sensor_type: [(ts, val), ...]}}


async def init_redis():
    global _redis
    _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    # 创建消费者组
    try:
        await _redis.xgroup_create(STREAM_SENSOR_DATA, CONSUMER_GROUP, id="0", mkstream=True)
    except Exception:
        pass  # 组已存在


async def init_db():
    global _pool
    _pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=2, max_size=5)


@app.on_event("startup")
async def startup():
    await init_redis()
    await init_db()
    asyncio.create_task(consume_loop())


@app.on_event("shutdown")
async def shutdown():
    if _redis:
        await _redis.close()
    if _pool:
        await _pool.close()


async def consume_loop():
    """持续消费 Redis Streams 传感器数据"""
    while True:
        try:
            results = await _redis.xreadgroup(
                CONSUMER_GROUP,
                "worker-1",
                {STREAM_SENSOR_DATA: ">"},
                count=50,
                block=1000,
            )
            if results:
                for _stream, messages in results:
                    for msg_id, fields in messages:
                        await process_message(fields)
                        await _redis.xack(STREAM_SENSOR_DATA, CONSUMER_GROUP, msg_id)
        except Exception as e:
            print(f"[StreamProcessor] 消费错误: {e}")
            await asyncio.sleep(1)


async def process_message(fields: dict):
    """处理单条传感器数据"""
    device_id = fields.get("device_id", "")
    timestamp_str = fields.get("timestamp", "")
    sensors_str = fields.get("sensors", "{}")
    status = fields.get("status", "running")

    try:
        sensors = json.loads(sensors_str)
    except json.JSONDecodeError:
        return

    # 解析时间
    try:
        ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    except Exception:
        ts = datetime.now(timezone.utc)

    # 1. 写入 TimescaleDB sensor_readings
    await write_sensor_readings(device_id, ts, sensors, status)

    # 2. 更新设备运行时数据
    update_device_runtime(device_id, status)

    # 3. 更新滑动窗口
    for sensor_name, value in sensors.items():
        window_data[device_id][sensor_name].append((ts, value))
        # 只保留最近 60 条
        if len(window_data[device_id][sensor_name]) > 60:
            window_data[device_id][sensor_name] = window_data[device_id][sensor_name][-60:]

    # 4. 每分钟计算一次 OEE
    if int(ts.timestamp()) % 60 == 0:
        await calculate_and_publish_oee(device_id, ts)


async def write_sensor_readings(device_id: str, ts: datetime, sensors: dict, status: str):
    """批量写入传感器读数到 TimescaleDB"""
    async with _pool.acquire() as conn:
        rows = [(ts, device_id, s_type, val, status) for s_type, val in sensors.items()]
        await conn.executemany(
            "INSERT INTO sensor_readings (time, device_id, sensor_type, value, status) VALUES ($1, $2, $3, $4, $5)",
            rows,
        )


def update_device_runtime(device_id: str, status: str):
    """更新设备运行时间"""
    if device_id not in device_runtime:
        device_runtime[device_id] = {
            "start_time": datetime.now(timezone.utc).timestamp(),
            "running_secs": 0,
            "output": 0,
            "defects": 0,
        }
    if status == "running":
        device_runtime[device_id]["running_secs"] += 1
        # 模拟产量（每台设备每秒产出约 0.1 个产品）
        import random
        if random.random() < 0.1:
            device_runtime[device_id]["output"] += 1
            # 模拟 2% 不良率
            if random.random() < 0.02:
                device_runtime[device_id]["defects"] += 1


async def calculate_and_publish_oee(device_id: str, ts: datetime):
    """计算 OEE 并发布"""
    rt = device_runtime.get(device_id, {})
    total_secs = max(1, datetime.now(timezone.utc).timestamp() - rt.get("start_time", 0))
    running_secs = rt.get("running_secs", 0)
    output = rt.get("output", 0)
    defects = rt.get("defects", 0)

    availability = min(1.0, running_secs / total_secs) if total_secs > 0 else 0
    # 理论产量 = 运行时间 * 0.1 (每10秒1个)
    theoretical_output = max(1, running_secs / 10)
    performance = min(1.0, output / theoretical_output) if theoretical_output > 0 else 0
    quality = (output - defects) / output if output > 0 else 1.0
    oee = availability * performance * quality

    oee_data = {
        "time": ts.isoformat(),
        "device_id": device_id,
        "availability": round(availability, 4),
        "performance": round(performance, 4),
        "quality": round(quality, 4),
        "oee": round(oee, 4),
        "output_count": output,
        "defect_count": defects,
    }

    # 写入 TimescaleDB
    async with _pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO oee_metrics (time, device_id, availability, performance, quality, oee, output_count, defect_count)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
            ts, device_id, oee_data["availability"], oee_data["performance"],
            oee_data["quality"], oee_data["oee"], output, defects,
        )

    # 发布到 Pub/Sub
    await _redis.publish(CHANNEL_OEE_UPDATE, json.dumps(oee_data))


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "stream_processor"}


@app.get("/api/v1/stream/window/{device_id}")
async def get_window_data(device_id: str):
    """获取设备最近的滑动窗口数据"""
    data = {}
    for sensor, values in window_data.get(device_id, {}).items():
        data[sensor] = [{"time": v[0].isoformat(), "value": v[1]} for v in values[-20:]]
    return {"device_id": device_id, "sensors": data}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
