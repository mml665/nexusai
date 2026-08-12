"""工厂模型定义 - 3条产线 9台设备"""

DEVICES = [
    # 产线 A
    {
        "device_id": "CNC-A01",
        "name": "CNC加工中心A01",
        "line": "A",
        "type": "CNC",
        "sensors": {
            "temperature":   {"unit": "C",    "normal_min": 40,  "normal_max": 55,  "base": 45,  "noise": 1.5},
            "vibration":     {"unit": "mm/s", "normal_min": 0.1, "normal_max": 0.3, "base": 0.15, "noise": 0.02},
            "spindle_speed": {"unit": "RPM",  "normal_min": 2800,"normal_max": 3200,"base": 3000, "noise": 30},
            "cutting_force": {"unit": "N",    "normal_min": 100, "normal_max": 150, "base": 120, "noise": 5},
        },
    },
    {
        "device_id": "CNC-A02",
        "name": "CNC加工中心A02",
        "line": "A",
        "type": "CNC",
        "sensors": {
            "temperature":   {"unit": "C",    "normal_min": 40,  "normal_max": 55,  "base": 46,  "noise": 1.5},
            "vibration":     {"unit": "mm/s", "normal_min": 0.1, "normal_max": 0.3, "base": 0.16, "noise": 0.02},
            "spindle_speed": {"unit": "RPM",  "normal_min": 2800,"normal_max": 3200,"base": 3000, "noise": 30},
            "cutting_force": {"unit": "N",    "normal_min": 100, "normal_max": 150, "base": 125, "noise": 5},
        },
    },
    {
        "device_id": "ROBOT-A01",
        "name": "机械臂A01",
        "line": "A",
        "type": "Robot",
        "sensors": {
            "temperature":         {"unit": "C",   "normal_min": 35,  "normal_max": 50,  "base": 40,  "noise": 1.0},
            "vibration":           {"unit": "mm/s","normal_min": 0.05,"normal_max": 0.2, "base": 0.1, "noise": 0.01},
            "current":             {"unit": "A",   "normal_min": 8,   "normal_max": 12,  "base": 10,  "noise": 0.3},
            "position_accuracy":   {"unit": "mm",  "normal_min": 0.01,"normal_max": 0.05,"base": 0.02,"noise": 0.003},
        },
    },
    # 产线 B
    {
        "device_id": "PRESS-B01",
        "name": "液压机B01",
        "line": "B",
        "type": "Press",
        "sensors": {
            "temperature":        {"unit": "C",   "normal_min": 35,  "normal_max": 55,  "base": 42,  "noise": 1.5},
            "hydraulic_pressure": {"unit": "MPa", "normal_min": 20,  "normal_max": 28,  "base": 25,  "noise": 0.5},
            "pressure":           {"unit": "MPa", "normal_min": 20,  "normal_max": 28,  "base": 25,  "noise": 0.5},
            "stroke":             {"unit": "mm",  "normal_min": 95,  "normal_max": 105, "base": 100, "noise": 1.0},
        },
    },
    {
        "device_id": "PRESS-B02",
        "name": "液压机B02",
        "line": "B",
        "type": "Press",
        "sensors": {
            "temperature":        {"unit": "C",   "normal_min": 35,  "normal_max": 55,  "base": 41,  "noise": 1.5},
            "hydraulic_pressure": {"unit": "MPa", "normal_min": 20,  "normal_max": 28,  "base": 24,  "noise": 0.5},
            "pressure":           {"unit": "MPa", "normal_min": 20,  "normal_max": 28,  "base": 24,  "noise": 0.5},
            "stroke":             {"unit": "mm",  "normal_min": 95,  "normal_max": 105, "base": 100, "noise": 1.0},
        },
    },
    {
        "device_id": "CONV-B01",
        "name": "传送带B01",
        "line": "B",
        "type": "Conveyor",
        "sensors": {
            "temperature": {"unit": "C",   "normal_min": 30,  "normal_max": 45,  "base": 35,  "noise": 1.0},
            "rpm":         {"unit": "RPM", "normal_min": 55,  "normal_max": 65,  "base": 60,  "noise": 1.0},
            "current":     {"unit": "A",   "normal_min": 3,   "normal_max": 6,   "base": 4.5, "noise": 0.2},
            "speed":       {"unit": "m/s", "normal_min": 0.8, "normal_max": 1.2, "base": 1.0, "noise": 0.03},
        },
    },
    # 产线 C
    {
        "device_id": "OVEN-C01",
        "name": "工业炉C01",
        "line": "C",
        "type": "Oven",
        "sensors": {
            "temperature": {"unit": "C",   "normal_min": 180, "normal_max": 220, "base": 200, "noise": 3.0},
            "gas_flow":    {"unit": "m3/h","normal_min": 8,   "normal_max": 12,  "base": 10,  "noise": 0.3},
            "pressure":    {"unit": "kPa", "normal_min": 95,  "normal_max": 105, "base": 100, "noise": 1.0},
            "door_status": {"unit": "",    "normal_min": 0,   "normal_max": 1,   "base": 0,   "noise": 0},
        },
    },
    {
        "device_id": "COOLER-C01",
        "name": "冷却器C01",
        "line": "C",
        "type": "Cooler",
        "sensors": {
            "temperature":    {"unit": "C",   "normal_min": 5,   "normal_max": 15,  "base": 10,  "noise": 0.8},
            "flow_rate":      {"unit": "L/min","normal_min": 40,  "normal_max": 60,  "base": 50,  "noise": 1.5},
            "pressure":       {"unit": "kPa", "normal_min": 200, "normal_max": 300, "base": 250, "noise": 5.0},
            "valve_position": {"unit": "%",   "normal_min": 60,  "normal_max": 80,  "base": 70,  "noise": 1.5},
        },
    },
    {
        "device_id": "ROBOT-C01",
        "name": "机械臂C01",
        "line": "C",
        "type": "Robot",
        "sensors": {
            "temperature":       {"unit": "C",   "normal_min": 35,  "normal_max": 50,  "base": 38,  "noise": 1.0},
            "vibration":         {"unit": "mm/s","normal_min": 0.05,"normal_max": 0.2, "base": 0.08,"noise": 0.01},
            "current":           {"unit": "A",   "normal_min": 8,   "normal_max": 12,  "base": 9,   "noise": 0.3},
            "position_accuracy": {"unit": "mm",  "normal_min": 0.01,"normal_max": 0.05,"base": 0.02,"noise": 0.003},
        },
    },
]

DEVICE_MAP = {d["device_id"]: d for d in DEVICES}
