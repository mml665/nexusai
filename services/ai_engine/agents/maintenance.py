"""
Agent 2: 预测性维护引擎（趋势分析 + RUL 预测）

方法：
1. 从 TimescaleDB 拉取设备最近 N 小时的传感器时序数据
2. 对关键传感器（振动、温度等）做线性回归趋势分析
3. 根据趋势斜率预测剩余寿命（RUL）
4. 计算综合健康度评分（0-100）
5. 输出维护建议写入 maintenance_predictions 表

触发方式：
- 定时执行（每 5 分钟）
- 异常事件触发
- API 手动触发
"""

import asyncpg
import math
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass

# ── 关键传感器及恶化方向 ──────────────────────────────────────
# sensor_type -> (weight, direction)
# direction: +1 表示值越大越差, -1 表示值越小越差
DEGRADATION_SENSORS = {
    "vibration":           {"weight": 0.35, "direction": 1, "limit": 0.8,  "base": 0.15},
    "temperature":         {"weight": 0.25, "direction": 1, "limit": 80,   "base": 45},
    "current":             {"weight": 0.20, "direction": 1, "limit": 18,   "base": 10},
    "hydraulic_pressure":  {"weight": 0.30, "direction": -1, "limit": 15,  "base": 25},
    "pressure":            {"weight": 0.25, "direction": -1, "limit": 15,  "base": 25},
    "position_accuracy":   {"weight": 0.30, "direction": 1, "limit": 0.15, "base": 0.02},
    "flow_rate":           {"weight": 0.25, "direction": -1, "limit": 30,  "base": 50},
}

# RUL 预测的时间范围（小时）
RUL_HORIZON_HOURS = 720  # 30 天最大预测


@dataclass
class MaintenanceResult:
    """维护预测结果"""
    device_id: str
    health_score: int
    predicted_rul: Optional[int]       # 剩余寿命（小时），None = 无法预测
    risk_level: str                    # healthy / low / medium / high / critical
    recommendation: str
    trends: dict                       # 各传感器趋势详情
    analyzed_at: str


def _linear_regression(values: list[float]) -> tuple[float, float, float]:
    """
    简单线性回归 y = a*x + b
    Returns: (slope, intercept, r_squared)
    """
    n = len(values)
    if n < 3:
        return 0.0, values[0] if values else 0.0, 0.0

    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n

    ss_xx = sum((x - mean_x) ** 2 for x in xs)
    ss_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values))

    if ss_xx == 0:
        return 0.0, mean_y, 0.0

    slope = ss_xy / ss_xx
    intercept = mean_y - slope * mean_x

    # R²
    ss_yy = sum((y - mean_y) ** 2 for y in values)
    if ss_yy == 0:
        r_squared = 1.0 if slope == 0 else 0.0
    else:
        r_squared = (ss_xy ** 2) / (ss_xx * ss_yy)

    return slope, intercept, r_squared


def _predict_rul(current_value: float, slope: float, limit_value: float, direction: int) -> Optional[int]:
    """
    根据当前值、趋势斜率和极限值预测剩余寿命（小时）

    Args:
        current_value: 当前传感器值
        slope: 每小时变化量
        limit_value: 失效阈值
        direction: +1 增大失效, -1 减小失效

    Returns:
        剩余寿命（小时），如果趋势不明显返回 None
    """
    if abs(slope) < 1e-8:
        return None

    if direction > 0:
        # 值在增大，趋于 limit
        if slope <= 0:
            return None  # 在好转
        remaining = (limit_value - current_value) / slope
    else:
        # 值在减小，趋于 limit
        if slope >= 0:
            return None  # 在好转
        remaining = (current_value - limit_value) / abs(slope)

    if remaining <= 0:
        return 0  # 已超限
    if remaining > RUL_HORIZON_HOURS:
        return RUL_HORIZON_HOURS

    return int(remaining)


def _health_score_from_rul(rul_hours: Optional[int]) -> int:
    """根据 RUL 计算健康度"""
    if rul_hours is None:
        return 90
    if rul_hours <= 0:
        return 10
    if rul_hours >= RUL_HORIZON_HOURS:
        return 95
    # 对数衰减：快到极限时分数快速下降
    ratio = rul_hours / RUL_HORIZON_HOURS
    score = int(10 + 85 * (ratio ** 0.3))
    return max(10, min(95, score))


def _risk_level(score: int) -> str:
    if score >= 80:
        return "healthy"
    if score >= 60:
        return "low"
    if score >= 40:
        return "medium"
    if score >= 20:
        return "high"
    return "critical"


def _recommendation(score: int, risk: str, worst_sensor: Optional[str], rul: Optional[int]) -> str:
    if risk == "healthy":
        return "设备运行正常，继续保持当前维保计划。"
    if risk == "low":
        return f"设备状态良好，{worst_sensor}有轻微劣化趋势，建议下次计划维护时重点关注。"
    if risk == "medium":
        if rul:
            return f"设备健康度下降，{worst_sensor}趋势明显。预计剩余寿命约{rul}小时，建议在2周内安排预防性维护。"
        return f"设备健康度下降，{worst_sensor}趋势明显，建议在2周内安排预防性维护。"
    if risk == "high":
        if rul:
            return f"设备风险较高！{worst_sensor}劣化严重，预计剩余寿命仅{rul}小时。建议立即创建维护工单，在72小时内安排检修。"
        return f"设备风险较高！{worst_sensor}劣化严重，建议立即创建维护工单，在72小时内安排检修。"
    # critical
    return f"设备处于危险状态！{worst_sensor}已接近失效阈值，建议立即停机检修，避免设备损坏和生产事故。"


async def run_maintenance_analysis(
    pool: asyncpg.Pool,
    device_id: str,
    lookback_hours: int = 2,
) -> MaintenanceResult:
    """
    对指定设备执行预测性维护分析

    1. 查询 TimescaleDB 最近 N 小时的传感器数据
    2. 对关键传感器做线性回归
    3. 预测 RUL
    4. 计算健康度
    5. 写入 maintenance_predictions 表
    """
    async with pool.acquire() as conn:
        # 拉取最近 N 小时的传感器数据，按 sensor_type 分组
        rows = await conn.fetch(
            """
            SELECT sensor_type, value, time
            FROM sensor_readings
            WHERE device_id = $1
              AND time > NOW() - INTERVAL '%s hours'
            ORDER BY time ASC
            """ % lookback_hours,
            device_id,
        )

    if not rows:
        # 无数据，返回默认健康状态
        return MaintenanceResult(
            device_id=device_id,
            health_score=95,
            predicted_rul=None,
            risk_level="healthy",
            recommendation="设备无历史数据，默认健康状态。",
            trends={},
            analyzed_at=datetime.now(timezone.utc).isoformat(),
        )

    # 按 sensor_type 分组
    sensor_data: dict[str, list[float]] = {}
    for row in rows:
        st = row["sensor_type"]
        if st not in sensor_data:
            sensor_data[st] = []
        sensor_data[st].append(float(row["value"]))

    # 采样频率约 1/秒，数据量大时降采样（每 10 个取 1 个均值）
    for st in sensor_data:
        vals = sensor_data[st]
        if len(vals) > 200:
            step = len(vals) // 200
            sensor_data[st] = [sum(vals[i:i+step]) / step for i in range(0, len(vals), step)]

    # 对关键传感器做趋势分析
    trends = {}
    rul_predictions: list[tuple[str, float, int]] = []  # (sensor_type, weight, rul_hours)
    sensor_scores: list[tuple[str, float, int]] = []    # (sensor_type, weight, score)

    for sensor_type, config in DEGRADATION_SENSORS.items():
        if sensor_type not in sensor_data:
            continue

        values = sensor_data[sensor_type]
        if len(values) < 3:
            continue

        slope, intercept, r2 = _linear_regression(values)
        current_value = values[-1]

        # 数据点间隔（秒）→ 转换为每小时变化率
        # 假设约 1 秒 1 个点（降采样后可能不同），用实际时间差
        # 简化：用采样数 / lookback_hours 估算每小时点数
        points_per_hour = max(len(values) / lookback_hours, 1)
        slope_per_hour = slope * points_per_hour

        rul = _predict_rul(
            current_value=current_value,
            slope=slope_per_hour,
            limit_value=config["limit"],
            direction=config["direction"],
        )

        trends[sensor_type] = {
            "current": round(current_value, 3),
            "base": config["base"],
            "limit": config["limit"],
            "slope_per_hour": round(slope_per_hour, 6),
            "r_squared": round(r2, 4),
            "rul_hours": rul,
            "trend": "rising" if slope_per_hour > 0 else ("falling" if slope_per_hour < 0 else "stable"),
        }

        if rul is not None:
            rul_predictions.append((sensor_type, config["weight"], rul))

        score = _health_score_from_rul(rul)
        sensor_scores.append((sensor_type, config["weight"], score))

    # 加权综合健康度
    if sensor_scores:
        total_weight = sum(w for _, w, _ in sensor_scores)
        if total_weight > 0:
            health_score = int(sum(s * w for _, w, s in sensor_scores) / total_weight)
        else:
            health_score = 90
    else:
        health_score = 90

    # 取最短 RUL 作为设备 RUL
    if rul_predictions:
        worst = min(rul_predictions, key=lambda x: x[2])
        predicted_rul = worst[2]
        worst_sensor = worst[0]
    else:
        predicted_rul = None
        # 找权重最低分的传感器
        if sensor_scores:
            worst = min(sensor_scores, key=lambda x: x[2])
            worst_sensor = worst[0]
        else:
            worst_sensor = None

    risk = _risk_level(health_score)
    recommendation = _recommendation(health_score, risk, worst_sensor, predicted_rul)

    result = MaintenanceResult(
        device_id=device_id,
        health_score=health_score,
        predicted_rul=predicted_rul,
        risk_level=risk,
        recommendation=recommendation,
        trends=trends,
        analyzed_at=datetime.now(timezone.utc).isoformat(),
    )

    # 写入数据库
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO maintenance_predictions
                (device_id, health_score, predicted_rul, risk_level, recommendation)
            VALUES ($1, $2, $3, $4, $5)
            """,
            device_id,
            health_score,
            predicted_rul,
            risk,
            recommendation,
        )

    return result
