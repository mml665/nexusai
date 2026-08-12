"""事件类型常量"""

# Redis Streams
STREAM_SENSOR_DATA = "sensor_data"

# Redis Pub/Sub channels
CHANNEL_OEE_UPDATE = "oee_update"
CHANNEL_ANOMALY = "anomaly_detected"
CHANNEL_DIAGNOSIS = "diagnosis_complete"
CHANNEL_ALERT = "alert_triggered"
CHANNEL_DEVICE_STATUS = "device_status"

# 设备状态
STATUS_RUNNING = "running"
STATUS_IDLE = "idle"
STATUS_MAINTENANCE = "maintenance"
STATUS_FAULT = "fault"

# 告警级别
SEVERITY_CRITICAL = "critical"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

# 告警类型
ALERT_FAULT = "fault"
ALERT_QUALITY = "quality"
ALERT_SAFETY = "safety"
