// ── 通用类型定义 ──

export interface DeviceInfo {
  device_id: string;
  name: string;
  line: string;
  type: string;
  sensors: string[];
  status: string;
  installed_at?: string;
}

export interface SensorReading {
  device_id: string;
  timestamp: string;
  sensors: Record<string, number>;
  status: string;
}

export interface OEEData {
  time: string;
  device_id: string;
  availability: number;
  performance: number;
  quality: number;
  oee: number;
  output_count: number;
  defect_count: number;
}

export interface AlertData {
  id: number;
  device_id: string;
  type: string;
  severity: string;
  title: string;
  description: string;
  status: string;
  created_at: string;
  resolved_at?: string;
}

export interface DiagnosisData {
  device_id: string;
  anomaly_type: string;
  diagnosis: string;
  recommendation: string;
  urgency: string;
  rag_sources: any[];
  llm_used: boolean;
  sensor_data: Record<string, number>;
  timestamp: string;
}

export interface MaintenanceData {
  device_id: string;
  health_score: number;
  predicted_rul: number | null;
  risk_level: string;
  recommendation: string;
  trends?: Record<string, any>;
  analyzed_at?: string;
}

export interface OverviewData {
  timestamp: string;
  summary: {
    total_devices: number;
    running_devices: number;
    avg_oee: number;
    total_output: number;
    total_defects: number;
    defect_rate: number;
    active_alerts: number;
  };
  devices: DeviceInfo[];
  oee_by_device: Array<{
    device_id: string;
    oee: number;
    availability: number;
    performance: number;
    quality: number;
    output_count: number;
    defect_count: number;
  }>;
  recent_diagnoses: Array<{
    device_id: string;
    anomaly_type: string;
    urgency: string;
    created_at: string;
  }>;
}

export interface AnomalyEvent {
  device_id: string;
  sensor_type: string;
  value: number;
  anomaly_type: string;
  severity: string;
  message: string;
  timestamp: string;
  context: Record<string, any>;
  sensor_data: Record<string, number>;
}

export interface FaultType {
  name: string;
  label: string;
  description: string;
}

// ── 设备配置（前端常量） ──

export const DEVICE_LIST = [
  "CNC-A01", "CNC-A02", "ROBOT-A01",
  "PRESS-B01", "PRESS-B02", "CONV-B01",
  "OVEN-C01", "COOLER-C01", "ROBOT-C01",
];

export const LINE_COLORS: Record<string, string> = {
  A: "#3b82f6",
  B: "#f59e0b",
  C: "#10b981",
};

export const SEVERITY_COLORS: Record<string, string> = {
  critical: "#ef4444",
  warning: "#f59e0b",
  info: "#3b82f6",
};

export const RISK_COLORS: Record<string, string> = {
  healthy: "#10b981",
  low: "#84cc16",
  medium: "#f59e0b",
  high: "#f97316",
  critical: "#ef4444",
};

// ── 中文标签映射 ──

export const SEVERITY_LABELS: Record<string, string> = {
  critical: "严重",
  warning: "警告",
  info: "信息",
};

export const ALERT_STATUS_LABELS: Record<string, string> = {
  triggered: "已触发",
  acknowledged: "已确认",
  resolved: "已解决",
  false_alarm: "误报",
};

export const URGENCY_LABELS: Record<string, string> = {
  critical: "紧急",
  warning: "警告",
  info: "信息",
};

export const RISK_LABELS: Record<string, string> = {
  healthy: "健康",
  low: "低风险",
  medium: "中风险",
  high: "高风险",
  critical: "严重",
};

export const TREND_LABELS: Record<string, string> = {
  rising: "↑ 上升",
  falling: "↓ 下降",
  stable: "→ 稳定",
};

export const FAULT_TYPE_LABELS: Record<string, string> = {
  bearing_wear: "轴承磨损",
  overheating: "过热",
  calibration_drift: "校准漂移",
  hydraulic_leak: "液压泄漏",
  electrical_fault: "电气故障",
};

export const ROLE_LABELS: Record<string, string> = {
  admin: "管理员",
  operator: "操作员",
  viewer: "观察者",
};

export const SENSOR_LABELS: Record<string, string> = {
  temperature: "温度",
  vibration: "振动",
  current: "电流",
  pressure: "压力",
  rpm: "转速",
  speed: "速度",
  power: "功率",
  humidity: "湿度",
  flow_rate: "流量",
  torque: "扭矩",
};

/** 通用翻译函数：找不到映射时返回原值 */
export function t(map: Record<string, string>, key: string): string {
  return map[key] || key;
}
