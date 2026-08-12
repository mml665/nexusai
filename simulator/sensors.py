"""传感器数据生成 - 模拟真实传感器读数"""
import random
import math
import time
from datetime import datetime, timezone

# 每个设备的传感器状态（保留上一轮值，模拟连续变化）
_device_state: dict = {}

def _get_state(device_id: str) -> dict:
    if device_id not in _device_state:
        _device_state[device_id] = {}
    return _device_state[device_id]


def generate_reading(device: dict, active_faults: dict) -> dict:
    """生成一台设备的传感器读数

    Args:
        device: 设备配置
        active_faults: {device_id: {sensor_type: fault_config}}

    Returns: 传感器读数字典
    """
    device_id = device["device_id"]
    state = _get_state(device_id)
    readings = {}
    status = "running"

    for sensor_name, sensor_cfg in device["sensors"].items():
        base = sensor_cfg["base"]
        noise = sensor_cfg["noise"]

        # 生成基础值（带随机噪声 + 缓慢漂移）
        prev = state.get(sensor_name, base)
        drift = random.gauss(0, noise * 0.3)
        value = prev + drift

        # 均值回归（防止漂移太远）
        value = value * 0.95 + base * 0.05

        # 应用故障影响
        fault = active_faults.get(device_id, {}).get(sensor_name)
        if fault:
            fault_type = fault["type"]
            if fault_type == "gradual_increase":
                # 渐增型故障（如轴承磨损导致振动渐增）
                elapsed = time.time() - fault["start_time"]
                value = base + fault["rate"] * elapsed + random.gauss(0, noise)
            elif fault_type == "sudden_spike":
                # 突增型故障（如过热）
                value = fault["target"] + random.gauss(0, noise * 2)
            elif fault_type == "drift":
                # 漂移型故障（如校准漂移）
                elapsed = time.time() - fault["start_time"]
                value = base + fault["rate"] * elapsed
            elif fault_type == "sudden_drop":
                # 骤降型故障（如液压泄漏）
                value = fault["target"] + random.gauss(0, noise * 2)

            status = "fault"

        # door_status 是离散值
        if sensor_name == "door_status":
            value = 0  # 0=closed, 1=open

        # 保留状态
        state[sensor_name] = value

        # 判断是否超范围
        normal = sensor_cfg["normal_min"] <= value <= sensor_cfg["normal_max"]
        readings[sensor_name] = round(value, 4)

    return {
        "device_id": device_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sensors": readings,
        "status": status,
    }
