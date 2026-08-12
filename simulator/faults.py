"""故障注入逻辑 - 模拟设备故障"""

# 故障类型定义
FAULT_TYPES = {
    "bearing_wear": {
        "name": "轴承磨损",
        "description": "振动值逐渐增大，伴随温度缓慢上升",
        "applicable_devices": ["CNC-A01", "CNC-A02", "ROBOT-A01", "ROBOT-C01"],
        "sensor_effects": {
            "vibration": {"type": "gradual_increase", "rate": 0.002},  # 每秒增加0.002
            "temperature": {"type": "gradual_increase", "rate": 0.01},  # 每秒增加0.01
        },
    },
    "overheating": {
        "name": "过热",
        "description": "温度突然升高超过安全阈值",
        "applicable_devices": ["CNC-A01", "CNC-A02", "OVEN-C01", "PRESS-B01", "PRESS-B02"],
        "sensor_effects": {
            "temperature": {"type": "sudden_spike", "target": 90},
        },
    },
    "calibration_drift": {
        "name": "校准漂移",
        "description": "转速/位置精度逐渐偏离设定值",
        "applicable_devices": ["CNC-A01", "CNC-A02", "ROBOT-A01", "ROBOT-C01"],
        "sensor_effects": {
            "spindle_speed": {"type": "drift", "rate": 0.5},
            "position_accuracy": {"type": "drift", "rate": 0.0001},
        },
    },
    "hydraulic_leak": {
        "name": "液压泄漏",
        "description": "压力骤降，液压系统失效",
        "applicable_devices": ["PRESS-B01", "PRESS-B02"],
        "sensor_effects": {
            "hydraulic_pressure": {"type": "sudden_drop", "target": 12},
            "pressure": {"type": "sudden_drop", "target": 12},
        },
    },
    "electrical_fault": {
        "name": "电气故障",
        "description": "电流异常飙升",
        "applicable_devices": ["ROBOT-A01", "CONV-B01", "ROBOT-C01"],
        "sensor_effects": {
            "current": {"type": "sudden_spike", "target": 25},
        },
    },
}

# 活跃的故障状态: {device_id: {sensor_type: fault_config}}
_active_faults: dict = {}


def inject_fault(device_id: str, fault_type: str) -> dict:
    """注入故障

    Returns: {"success": bool, "message": str}
    """
    import time

    fault_def = FAULT_TYPES.get(fault_type)
    if not fault_def:
        return {"success": False, "message": f"未知故障类型: {fault_type}"}

    if device_id not in fault_def["applicable_devices"]:
        return {"success": False, "message": f"故障 {fault_def['name']} 不适用于设备 {device_id}"}

    if device_id not in _active_faults:
        _active_faults[device_id] = {}

    for sensor, effect in fault_def["sensor_effects"].items():
        effect_config = {**effect, "start_time": time.time(), "fault_type": fault_type}
        _active_faults[device_id][sensor] = effect_config

    return {
        "success": True,
        "message": f"已向设备 {device_id} 注入故障: {fault_def['name']}",
        "fault": fault_def["name"],
        "description": fault_def["description"],
    }


def clear_fault(device_id: str) -> dict:
    """清除设备所有故障"""
    if device_id in _active_faults:
        del _active_faults[device_id]
        return {"success": True, "message": f"已清除设备 {device_id} 的所有故障"}
    return {"success": False, "message": f"设备 {device_id} 无活跃故障"}


def clear_all_faults() -> dict:
    """清除所有故障"""
    count = sum(len(v) for v in _active_faults.values())
    _active_faults.clear()
    return {"success": True, "message": f"已清除所有故障 ({count} 个传感器)"}


def get_active_faults() -> dict:
    """获取当前活跃故障"""
    result = {}
    for device_id, sensors in _active_faults.items():
        result[device_id] = {
            sensor: cfg.get("fault_type", "unknown")
            for sensor, cfg in sensors.items()
        }
    return result
