"""工厂模拟器主服务 - 持续推送传感器数据 + 故障注入API"""
import asyncio
import httpx
import os
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from factory import DEVICES, DEVICE_MAP
from sensors import generate_reading
from faults import inject_fault, clear_fault, clear_all_faults, get_active_faults, FAULT_TYPES

app = FastAPI(title="NexusAI Factory Simulator", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8000")
PUSH_INTERVAL = float(os.getenv("PUSH_INTERVAL", "1.0"))
COLLECTOR_URL = os.getenv("COLLECTOR_URL", "http://iot_collector:8001")

# 共享故障状态（faults 模块内部管理）
from faults import _active_faults


class FaultRequest(BaseModel):
    device_id: str
    fault_type: str


@app.on_event("startup")
async def startup():
    asyncio.create_task(push_sensor_data_loop())


async def push_sensor_data_loop():
    """持续推送传感器数据到 IoT Collector"""
    async with httpx.AsyncClient() as client:
        while True:
            for device in DEVICES:
                reading = generate_reading(device, _active_faults)
                try:
                    await client.post(
                        f"{COLLECTOR_URL}/api/v1/sensors/data",
                        json=reading,
                        timeout=2.0,
                    )
                except Exception as e:
                    print(f"[Simulator] 推送失败 {device['device_id']}: {e}")
            await asyncio.sleep(PUSH_INTERVAL)


@app.get("/api/v1/simulator/status")
async def simulator_status():
    return {
        "status": "running",
        "device_count": len(DEVICES),
        "push_interval": PUSH_INTERVAL,
        "active_faults": get_active_faults(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/simulator/devices")
async def list_devices():
    return [
        {"device_id": d["device_id"], "name": d["name"], "line": d["line"], "type": d["type"]}
        for d in DEVICES
    ]


@app.get("/api/v1/simulator/faults/types")
async def list_fault_types():
    return {
        key: {
            "name": v["name"],
            "description": v["description"],
            "applicable_devices": v["applicable_devices"],
        }
        for key, v in FAULT_TYPES.items()
    }


@app.post("/api/v1/faults/inject")
async def api_inject_fault(req: FaultRequest):
    result = inject_fault(req.device_id, req.fault_type)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@app.delete("/api/v1/faults/{device_id}")
async def api_clear_fault(device_id: str):
    return clear_fault(device_id)


@app.delete("/api/v1/faults")
async def api_clear_all_faults():
    return clear_all_faults()


@app.get("/api/v1/faults/active")
async def api_get_faults():
    return get_active_faults()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8009)
