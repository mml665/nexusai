"""
Asset Manager — 设备资产管理

设备台账 CRUD、工单管理、用户与权限、操作审计

端口: 8007
"""

import json
import os
from datetime import datetime, timezone
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncpg
import uvicorn

app = FastAPI(title="NexusAI Asset Manager", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://nexusai:nexusai123@localhost:5432/nexusai")
_pool: asyncpg.Pool | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pool
    _pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=2, max_size=10)
    yield
    if _pool:
        await _pool.close()


app.router.lifespan_context = lifespan


# ═══════════════════════════════════════════════════════════════
#  Pydantic Models
# ═══════════════════════════════════════════════════════════════

class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    line: Optional[str] = None
    type: Optional[str] = None


class WorkOrderCreate(BaseModel):
    device_id: str
    type: str  # maintenance / repair / inspection / calibration
    priority: str = "medium"  # low / medium / high / urgent
    description: str = ""
    assigned_to: Optional[str] = None


class WorkOrderUpdate(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[str] = None
    description: Optional[str] = None


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "viewer"  # admin / operator / viewer


# ═══════════════════════════════════════════════════════════════
#  Health
# ═══════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "asset_manager"}


# ═══════════════════════════════════════════════════════════════
#  设备台账
# ═══════════════════════════════════════════════════════════════

@app.get("/api/v1/devices")
async def list_devices(line: Optional[str] = None, status: Optional[str] = None):
    """设备列表"""
    query = "SELECT id, device_id, name, line, type, sensors, status, installed_at, created_at FROM devices WHERE 1=1"
    params = []
    idx = 1
    if line:
        query += f" AND line = ${idx}"
        params.append(line)
        idx += 1
    if status:
        query += f" AND status = ${idx}"
        params.append(status)
        idx += 1
    query += " ORDER BY line, device_id"

    rows = await _pool.fetch(query, *params)
    return {
        "count": len(rows),
        "data": [
            {
                "id": r["id"],
                "device_id": r["device_id"],
                "name": r["name"],
                "line": r["line"],
                "type": r["type"],
                "sensors": r["sensors"],
                "status": r["status"],
                "installed_at": r["installed_at"].isoformat() if r["installed_at"] else None,
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ],
    }


@app.get("/api/v1/devices/{device_id}")
async def get_device(device_id: str):
    """设备详情"""
    row = await _pool.fetchrow(
        "SELECT id, device_id, name, line, type, sensors, status, installed_at, created_at FROM devices WHERE device_id = $1",
        device_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"设备 {device_id} 不存在")
    return {
        "id": row["id"],
        "device_id": row["device_id"],
        "name": row["name"],
        "line": row["line"],
        "type": row["type"],
        "sensors": row["sensors"],
        "status": row["status"],
        "installed_at": row["installed_at"].isoformat() if row["installed_at"] else None,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


@app.put("/api/v1/devices/{device_id}")
async def update_device(device_id: str, body: DeviceUpdate):
    """更新设备信息"""
    updates = []
    params = []
    idx = 1
    for field_name, value in body.dict(exclude_none=True).items():
        updates.append(f"{field_name} = ${idx}")
        params.append(value)
        idx += 1

    if not updates:
        raise HTTPException(status_code=400, detail="无更新字段")

    params.append(device_id)
    result = await _pool.execute(
        f"UPDATE devices SET {', '.join(updates)} WHERE device_id = ${idx}",
        *params,
    )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail=f"设备 {device_id} 不存在")

    # 审计日志
    await _pool.execute(
        "INSERT INTO audit_logs (action, resource, detail) VALUES ($1, $2, $3)",
        "update_device",
        f"device:{device_id}",
        json.dumps(body.dict(exclude_none=True)),
    )

    return {"device_id": device_id, "updated": True}


@app.get("/api/v1/devices/{device_id}/maintenance")
async def device_maintenance_history(device_id: str, limit: int = 10):
    """设备维保预测历史"""
    rows = await _pool.fetch(
        """
        SELECT id, device_id, health_score, predicted_rul, risk_level, recommendation, created_at
        FROM maintenance_predictions
        WHERE device_id = $1
        ORDER BY created_at DESC LIMIT $2
        """,
        device_id,
        limit,
    )
    return {
        "count": len(rows),
        "data": [
            {
                "id": r["id"],
                "device_id": r["device_id"],
                "health_score": r["health_score"],
                "predicted_rul": r["predicted_rul"],
                "risk_level": r["risk_level"],
                "recommendation": r["recommendation"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ],
    }


# ═══════════════════════════════════════════════════════════════
#  工单管理
# ═══════════════════════════════════════════════════════════════

@app.get("/api/v1/workorders")
async def list_workorders(
    status: Optional[str] = None,
    device_id: Optional[str] = None,
    limit: int = 50,
):
    """工单列表"""
    query = "SELECT id, device_id, type, priority, status, description, assigned_to, created_at, completed_at FROM work_orders WHERE 1=1"
    params = []
    idx = 1
    if status:
        query += f" AND status = ${idx}"
        params.append(status)
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
                "priority": r["priority"],
                "status": r["status"],
                "description": r["description"],
                "assigned_to": r["assigned_to"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
            }
            for r in rows
        ],
    }


@app.post("/api/v1/workorders")
async def create_workorder(body: WorkOrderCreate):
    """创建工单"""
    # 验证设备存在
    exists = await _pool.fetchval("SELECT 1 FROM devices WHERE device_id = $1", body.device_id)
    if not exists:
        raise HTTPException(status_code=404, detail=f"设备 {body.device_id} 不存在")

    wo_id = await _pool.fetchval(
        """
        INSERT INTO work_orders (device_id, type, priority, status, description, assigned_to)
        VALUES ($1, $2, $3, 'open', $4, $5)
        RETURNING id
        """,
        body.device_id,
        body.type,
        body.priority,
        body.description,
        body.assigned_to,
    )

    # 审计日志
    await _pool.execute(
        "INSERT INTO audit_logs (action, resource, detail) VALUES ($1, $2, $3)",
        "create_workorder",
        f"workorder:{wo_id}",
        json.dumps({"device_id": body.device_id, "type": body.type, "priority": body.priority}),
    )

    return {"id": wo_id, "status": "open", "device_id": body.device_id}


@app.put("/api/v1/workorders/{wo_id}")
async def update_workorder(wo_id: int, body: WorkOrderUpdate):
    """更新工单"""
    updates = []
    params = []
    idx = 1
    for field_name, value in body.dict(exclude_none=True).items():
        updates.append(f"{field_name} = ${idx}")
        params.append(value)
        idx += 1

    if not updates:
        raise HTTPException(status_code=400, detail="无更新字段")

    # 如果状态改为 completed，设置 completed_at
    if body.status == "completed":
        updates.append(f"completed_at = ${idx}")
        params.append(datetime.now(timezone.utc))
        idx += 1

    params.append(wo_id)
    result = await _pool.execute(
        f"UPDATE work_orders SET {', '.join(updates)} WHERE id = ${idx}",
        *params,
    )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="工单不存在")

    return {"id": wo_id, "updated": True}


# ═══════════════════════════════════════════════════════════════
#  用户管理（简化版 RBAC）
# ═══════════════════════════════════════════════════════════════

@app.get("/api/v1/users")
async def list_users():
    """用户列表"""
    rows = await _pool.fetch("SELECT id, username, role, created_at FROM users ORDER BY id")
    return {
        "count": len(rows),
        "data": [
            {
                "id": r["id"],
                "username": r["username"],
                "role": r["role"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ],
    }


@app.post("/api/v1/users")
async def create_user(body: UserCreate):
    """创建用户"""
    if body.role not in ("admin", "operator", "viewer"):
        raise HTTPException(status_code=400, detail="角色必须为 admin / operator / viewer")

    try:
        user_id = await _pool.fetchval(
            "INSERT INTO users (username, password, role) VALUES ($1, $2, $3) RETURNING id",
            body.username,
            body.password,  # 实际项目应 bcrypt 加密
            body.role,
        )
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=409, detail="用户名已存在")

    return {"id": user_id, "username": body.username, "role": body.role}


# ═══════════════════════════════════════════════════════════════
#  审计日志
# ═══════════════════════════════════════════════════════════════

@app.get("/api/v1/audit-logs")
async def list_audit_logs(limit: int = 50, action: Optional[str] = None):
    """审计日志"""
    if action:
        rows = await _pool.fetch(
            "SELECT id, user_id, action, resource, detail, created_at FROM audit_logs WHERE action = $1 ORDER BY created_at DESC LIMIT $2",
            action,
            limit,
        )
    else:
        rows = await _pool.fetch(
            "SELECT id, user_id, action, resource, detail, created_at FROM audit_logs ORDER BY created_at DESC LIMIT $1",
            limit,
        )
    return {
        "count": len(rows),
        "data": [
            {
                "id": r["id"],
                "user_id": r["user_id"],
                "action": r["action"],
                "resource": r["resource"],
                "detail": r["detail"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ],
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8007)
