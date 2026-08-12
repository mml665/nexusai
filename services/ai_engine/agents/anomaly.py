"""
Agent 1: 异常检测引擎（规则 + 统计，不用 LLM）

四种检测策略：
1. 静态阈值检测 — 超出设备手册规定的安全范围
2. 3σ 动态基线 — 偏离滚动均值 3 个标准差
3. 趋势检测 — 连续 N 点单调递增/递减
4. 变化率检测 — 单步跳变超过阈值

延迟目标：< 100ms（纯内存计算，无 IO）
"""

import time
from collections import deque
from typing import Optional
from dataclasses import dataclass, field, asdict
import math

# ── 设备传感器静态阈值（从工厂模型同步） ──────────────────────────────

DEVICE_THRESHOLDS = {
    "CNC-A01": {"temperature": (40, 80), "vibration": (0.1, 0.8), "spindle_speed": (2600, 3400), "cutting_force": (80, 180)},
    "CNC-A02": {"temperature": (40, 80), "vibration": (0.1, 0.8), "spindle_speed": (2600, 3400), "cutting_force": (80, 180)},
    "ROBOT-A01": {"temperature": (35, 70), "vibration": (0.05, 0.6), "current": (6, 18), "position_accuracy": (0.01, 0.15)},
    "PRESS-B01": {"temperature": (35, 80), "hydraulic_pressure": (15, 30), "pressure": (15, 30), "stroke": (90, 110)},
    "PRESS-B02": {"temperature": (35, 80), "hydraulic_pressure": (15, 30), "pressure": (15, 30), "stroke": (90, 110)},
    "CONV-B01": {"temperature": (30, 65), "rpm": (50, 70), "current": (2, 10), "speed": (0.7, 1.3)},
    "OVEN-C01": {"temperature": (180, 260), "gas_flow": (6, 15), "pressure": (90, 110), "door_status": (0, 1)},
    "COOLER-C01": {"temperature": (5, 25), "flow_rate": (30, 70), "pressure": (180, 320), "valve_position": (50, 90)},
    "ROBOT-C01": {"temperature": (35, 70), "vibration": (0.05, 0.6), "current": (6, 18), "position_accuracy": (0.01, 0.15)},
}

# 变化率阈值（单步绝对变化超过此值触发）
RATE_OF_CHANGE_THRESHOLD = {
    "temperature": 10.0,      # 10°C/step
    "vibration": 0.15,        # 0.15 mm/s/step
    "hydraulic_pressure": 8.0,
    "pressure": 8.0,
    "current": 3.0,
    "spindle_speed": 200,
    "cutting_force": 30,
    "rpm": 10,
    "speed": 0.2,
    "gas_flow": 3.0,
    "flow_rate": 15.0,
    "valve_position": 15.0,
    "position_accuracy": 0.05,
    "stroke": 5.0,
    "door_status": 1.0,
}

# 趋势检测：连续单调的点数
TREND_POINTS = 5
# 3σ 窗口大小
SIGMA_WINDOW = 30


@dataclass
class AnomalyEvent:
    """异常事件"""
    device_id: str
    sensor_type: str
    value: float
    anomaly_type: str         # threshold / sigma / trend / rate
    severity: str             # critical / warning
    message: str
    timestamp: str
    context: dict = field(default_factory=dict)


class DeviceBaseline:
    """单个设备-传感器的动态基线（滚动窗口统计）"""

    def __init__(self, window_size: int = SIGMA_WINDOW):
        self.window: deque[float] = deque(maxlen=window_size)

    def update(self, value: float):
        self.window.append(value)

    @property
    def mean(self) -> float:
        if len(self.window) < 5:
            return float("nan")
        return sum(self.window) / len(self.window)

    @property
    def std(self) -> float:
        n = len(self.window)
        if n < 5:
            return float("nan")
        m = self.mean
        return math.sqrt(sum((x - m) ** 2 for x in self.window) / n)

    @property
    def ready(self) -> bool:
        return len(self.window) >= 5


class AnomalyDetector:
    """
    异常检测引擎

    用法：
        detector = AnomalyDetector()
        events = detector.check(reading)
        for ev in events:
            # 发布到 Redis Pub/Sub
    """

    def __init__(self):
        # device_id -> sensor_type -> baseline
        self._baselines: dict[str, dict[str, DeviceBaseline]] = {}
        # device_id -> sensor_type -> recent values (for trend detection)
        self._history: dict[str, dict[str, deque]] = {}

    def _get_baseline(self, device_id: str, sensor_type: str) -> DeviceBaseline:
        if device_id not in self._baselines:
            self._baselines[device_id] = {}
        if sensor_type not in self._baselines[device_id]:
            self._baselines[device_id][sensor_type] = DeviceBaseline()
        return self._baselines[device_id][sensor_type]

    def _get_history(self, device_id: str, sensor_type: str) -> deque:
        if device_id not in self._history:
            self._history[device_id] = {}
        if sensor_type not in self._history[device_id]:
            self._history[device_id][sensor_type] = deque(maxlen=TREND_POINTS + 1)
        return self._history[device_id][sensor_type]

    def check(self, reading: dict) -> list[AnomalyEvent]:
        """
        对一条传感器读数执行全部四项检测

        Args:
            reading: {"device_id": ..., "timestamp": ..., "sensors": {sensor_type: value}, "status": ...}

        Returns:
            检测到的异常事件列表（可能为空）
        """
        device_id = reading["device_id"]
        timestamp = reading.get("timestamp", "")
        sensors = reading.get("sensors", {})
        events: list[AnomalyEvent] = []

        thresholds = DEVICE_THRESHOLDS.get(device_id, {})

        for sensor_type, value in sensors.items():
            if value is None:
                continue

            # 更新基线和历史
            baseline = self._get_baseline(device_id, sensor_type)
            baseline.update(value)

            history = self._get_history(device_id, sensor_type)
            prev_value = history[-1] if history else None
            history.append(value)

            # ── 1. 静态阈值检测 ──
            if sensor_type in thresholds:
                lo, hi = thresholds[sensor_type]
                if value > hi:
                    ratio = value / hi if hi != 0 else 999
                    severity = "critical" if ratio > 1.2 else "warning"
                    events.append(AnomalyEvent(
                        device_id=device_id,
                        sensor_type=sensor_type,
                        value=value,
                        anomaly_type="threshold",
                        severity=severity,
                        message=f"{device_id} {sensor_type}={value:.2f} 超出上限 {hi}",
                        timestamp=timestamp,
                        context={"threshold_min": lo, "threshold_max": hi, "ratio": round(ratio, 2)},
                    ))
                elif value < lo and sensor_type not in ("door_status",):
                    events.append(AnomalyEvent(
                        device_id=device_id,
                        sensor_type=sensor_type,
                        value=value,
                        anomaly_type="threshold",
                        severity="warning",
                        message=f"{device_id} {sensor_type}={value:.2f} 低于下限 {lo}",
                        timestamp=timestamp,
                        context={"threshold_min": lo, "threshold_max": hi},
                    ))

            # ── 2. 3σ 动态基线检测 ──
            if baseline.ready:
                mean = baseline.mean
                std = baseline.std
                if std > 0 and abs(value - mean) > 3 * std:
                    z_score = abs(value - mean) / std
                    events.append(AnomalyEvent(
                        device_id=device_id,
                        sensor_type=sensor_type,
                        value=value,
                        anomaly_type="sigma",
                        severity="warning" if z_score < 4 else "critical",
                        message=f"{device_id} {sensor_type}={value:.2f} 偏离基线 {z_score:.1f}σ (μ={mean:.2f}, σ={std:.2f})",
                        timestamp=timestamp,
                        context={"mean": round(mean, 3), "std": round(std, 3), "z_score": round(z_score, 2)},
                    ))

            # ── 3. 趋势检测（连续单调递增/递减） ──
            if len(history) >= TREND_POINTS:
                vals = list(history)[-TREND_POINTS:]
                if all(vals[i] < vals[i + 1] for i in range(len(vals) - 1)):
                    delta = vals[-1] - vals[0]
                    if abs(delta) > self._min_trend_delta(sensor_type):
                        direction = "上升" if delta > 0 else "下降"
                        events.append(AnomalyEvent(
                            device_id=device_id,
                            sensor_type=sensor_type,
                            value=value,
                            anomaly_type="trend",
                            severity="warning",
                            message=f"{device_id} {sensor_type} 连续{TREND_POINTS}点{direction} ({vals[0]:.2f}→{vals[-1]:.2f})",
                            timestamp=timestamp,
                            context={"trend": direction, "start": round(vals[0], 3), "end": round(vals[-1], 3), "delta": round(delta, 3)},
                        ))
                elif all(vals[i] > vals[i + 1] for i in range(len(vals) - 1)):
                    delta = vals[-1] - vals[0]
                    if abs(delta) > self._min_trend_delta(sensor_type):
                        events.append(AnomalyEvent(
                            device_id=device_id,
                            sensor_type=sensor_type,
                            value=value,
                            anomaly_type="trend",
                            severity="warning",
                            message=f"{device_id} {sensor_type} 连续{TREND_POINTS}点下降 ({vals[0]:.2f}→{vals[-1]:.2f})",
                            timestamp=timestamp,
                            context={"trend": "下降", "start": round(vals[0], 3), "end": round(vals[-1], 3), "delta": round(delta, 3)},
                        ))

            # ── 4. 变化率检测 ──
            if prev_value is not None:
                roc_threshold = RATE_OF_CHANGE_THRESHOLD.get(sensor_type, float("inf"))
                change = abs(value - prev_value)
                if change > roc_threshold:
                    events.append(AnomalyEvent(
                        device_id=device_id,
                        sensor_type=sensor_type,
                        value=value,
                        anomaly_type="rate",
                        severity="critical",
                        message=f"{device_id} {sensor_type} 突变 {prev_value:.2f}→{value:.2f} (Δ={change:.2f}, 阈值={roc_threshold})",
                        timestamp=timestamp,
                        context={"prev_value": round(prev_value, 3), "change": round(change, 3), "threshold": roc_threshold},
                    ))

        return events

    def _min_trend_delta(self, sensor_type: str) -> float:
        """趋势检测的最小有效变化量（过滤纯噪声波动）"""
        deltas = {
            "temperature": 3.0,
            "vibration": 0.05,
            "hydraulic_pressure": 2.0,
            "pressure": 2.0,
            "current": 0.5,
            "spindle_speed": 50,
            "cutting_force": 10,
            "rpm": 3,
            "speed": 0.05,
            "gas_flow": 0.5,
            "flow_rate": 3.0,
            "valve_position": 3.0,
            "position_accuracy": 0.01,
            "stroke": 1.0,
        }
        return deltas.get(sensor_type, 0.01)

    def get_device_health_summary(self, device_id: str) -> dict:
        """获取设备当前各传感器的基线状态（供 API 查询）"""
        result = {}
        if device_id in self._baselines:
            for sensor_type, baseline in self._baselines[device_id].items():
                result[sensor_type] = {
                    "mean": round(baseline.mean, 3) if not math.isnan(baseline.mean) else None,
                    "std": round(baseline.std, 3) if not math.isnan(baseline.std) else None,
                    "samples": len(baseline.window),
                }
        return result
