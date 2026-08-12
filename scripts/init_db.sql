-- NexusAI 数据库初始化
-- 启用时序扩展
CREATE EXTENSION IF NOT EXISTS timescaledb;
-- 启用向量扩展
CREATE EXTENSION IF NOT EXISTS vector;
-- 启用加密扩展（用于密码哈希）
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ==================== TimescaleDB 超表 ====================

-- 传感器读数
CREATE TABLE IF NOT EXISTS sensor_readings (
    time        TIMESTAMPTZ NOT NULL,
    device_id   TEXT NOT NULL,
    sensor_type TEXT NOT NULL,
    value       DOUBLE PRECISION NOT NULL,
    status      TEXT DEFAULT 'normal'
);
SELECT create_hypertable('sensor_readings', 'time', if_not_exists => TRUE);
CREATE INDEX idx_sensor_device ON sensor_readings (device_id, time DESC);
CREATE INDEX idx_sensor_type ON sensor_readings (sensor_type, time DESC);

-- OEE 指标
CREATE TABLE IF NOT EXISTS oee_metrics (
    time         TIMESTAMPTZ NOT NULL,
    device_id    TEXT NOT NULL,
    availability DOUBLE PRECISION,
    performance  DOUBLE PRECISION,
    quality      DOUBLE PRECISION,
    oee          DOUBLE PRECISION,
    output_count INTEGER DEFAULT 0,
    defect_count INTEGER DEFAULT 0
);
SELECT create_hypertable('oee_metrics', 'time', if_not_exists => TRUE);
CREATE INDEX idx_oee_device ON oee_metrics (device_id, time DESC);

-- ==================== PostgreSQL 业务表 ====================

-- 设备台账
CREATE TABLE IF NOT EXISTS devices (
    id           SERIAL PRIMARY KEY,
    device_id    TEXT UNIQUE NOT NULL,
    name         TEXT NOT NULL,
    line         TEXT NOT NULL,
    type         TEXT NOT NULL,
    sensors      JSONB NOT NULL,
    status       TEXT DEFAULT 'running',
    installed_at DATE DEFAULT CURRENT_DATE,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- 维保预测
CREATE TABLE IF NOT EXISTS maintenance_predictions (
    id              SERIAL PRIMARY KEY,
    device_id       TEXT NOT NULL,
    health_score    INTEGER NOT NULL,
    predicted_rul   INTEGER,
    risk_level      TEXT NOT NULL,
    recommendation  TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 诊断报告
CREATE TABLE IF NOT EXISTS diagnosis_reports (
    id             SERIAL PRIMARY KEY,
    device_id      TEXT NOT NULL,
    anomaly_type   TEXT NOT NULL,
    sensor_data    JSONB NOT NULL,
    diagnosis      TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    urgency        TEXT NOT NULL,
    rag_sources    JSONB,
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

-- 告警
CREATE TABLE IF NOT EXISTS alerts (
    id          SERIAL PRIMARY KEY,
    device_id   TEXT NOT NULL,
    type        TEXT NOT NULL,
    severity    TEXT NOT NULL,
    title       TEXT NOT NULL,
    description TEXT,
    status      TEXT DEFAULT 'triggered',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

-- 工单
CREATE TABLE IF NOT EXISTS work_orders (
    id          SERIAL PRIMARY KEY,
    device_id   TEXT NOT NULL,
    type        TEXT NOT NULL,
    priority    TEXT DEFAULT 'medium',
    status      TEXT DEFAULT 'open',
    description TEXT,
    assigned_to TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- 用户
CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    username    TEXT UNIQUE NOT NULL,
    password    TEXT NOT NULL,
    role        TEXT DEFAULT 'viewer',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 审计日志
CREATE TABLE IF NOT EXISTS audit_logs (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER,
    action      TEXT NOT NULL,
    resource    TEXT NOT NULL,
    detail      JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ==================== pgvector 知识库 ====================

CREATE TABLE IF NOT EXISTS knowledge_base (
    id          SERIAL PRIMARY KEY,
    title       TEXT NOT NULL,
    content     TEXT NOT NULL,
    category    TEXT NOT NULL,
    device_type TEXT,
    embedding   vector(1024)
);
CREATE INDEX IF NOT EXISTS idx_kb_embedding ON knowledge_base USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ==================== 初始数据 ====================

-- 默认用户（bcrypt 哈希，密码: admin123 / operator123 / viewer123）
INSERT INTO users (username, password, role) VALUES
    ('admin', crypt('admin123', gen_salt('bf', 12)), 'admin'),
    ('operator', crypt('operator123', gen_salt('bf', 12)), 'operator'),
    ('viewer', crypt('viewer123', gen_salt('bf', 12)), 'viewer')
ON CONFLICT (username) DO NOTHING;

-- 设备初始化
INSERT INTO devices (device_id, name, line, type, sensors) VALUES
    ('CNC-A01', 'CNC加工中心A01', 'A', 'CNC', '["temperature","vibration","spindle_speed","cutting_force"]'),
    ('CNC-A02', 'CNC加工中心A02', 'A', 'CNC', '["temperature","vibration","spindle_speed","cutting_force"]'),
    ('ROBOT-A01', '机械臂A01', 'A', 'Robot', '["temperature","vibration","current","position_accuracy"]'),
    ('PRESS-B01', '液压机B01', 'B', 'Press', '["temperature","hydraulic_pressure","pressure","stroke"]'),
    ('PRESS-B02', '液压机B02', 'B', 'Press', '["temperature","hydraulic_pressure","pressure","stroke"]'),
    ('CONV-B01', '传送带B01', 'B', 'Conveyor', '["temperature","rpm","current","speed"]'),
    ('OVEN-C01', '工业炉C01', 'C', 'Oven', '["temperature","gas_flow","pressure","door_status"]'),
    ('COOLER-C01', '冷却器C01', 'C', 'Cooler', '["temperature","flow_rate","pressure","valve_position"]'),
    ('ROBOT-C01', '机械臂C01', 'C', 'Robot', '["temperature","vibration","current","position_accuracy"]')
ON CONFLICT (device_id) DO NOTHING;

-- 知识库初始数据（设备手册摘要）
INSERT INTO knowledge_base (title, content, category, device_type) VALUES
    ('CNC轴承磨损诊断手册', 'CNC加工中心主轴轴承磨损的典型特征：振动值在低频段（1-10Hz）逐渐增大，伴随温度缓慢上升。诊断步骤：1. 检查振动频谱 2. 对比基线数据 3. 计算剩余寿命 4. 制定更换计划。严重时振动值超过0.8mm/s需立即停机。', 'manual', 'CNC'),
    ('CNC过热处理指南', 'CNC加工中心过热通常由冷却液不足、主轴负载过大或环境温度过高引起。处理步骤：1. 检查冷却液液位 2. 降低进给速度 3. 检查散热系统 4. 温度超过85°C必须停机冷却。', 'manual', 'CNC'),
    ('液压机液压泄漏诊断', '液压机压力骤降通常指示液压泄漏。诊断步骤：1. 检查液压管路 2. 检查密封件 3. 检查压力表 4. 压力低于额定值70%时停机检修。', 'manual', 'Press'),
    ('机械臂位置漂移校准', '机械臂位置精度下降通常由编码器漂移或机械松动引起。校准步骤：1. 运行自检程序 2. 对比标准位置 3. 调整编码器 4. 紧固机械连接。位置偏差超过0.1mm需重新校准。', 'manual', 'Robot'),
    ('工业炉温度控制异常', '工业炉温度异常可能由燃气流量不稳、热电偶故障或隔热层损坏引起。诊断步骤：1. 检查燃气流量 2. 校验热电偶 3. 检查隔热层 4. 温度偏差超过±10°C需停机检查。', 'manual', 'Oven'),
    ('传送带电机过载处理', '传送带电流异常升高通常由负载过大或轴承卡死引起。处理步骤：1. 检查负载 2. 检查轴承 3. 检查驱动电机 4. 电流超过额定值120%时停机。', 'manual', 'Conveyor'),
    ('冷却器流量异常诊断', '冷却器流量下降可能由管路堵塞、泵故障或阀门异常引起。诊断步骤：1. 检查过滤器 2. 检查泵运行状态 3. 检查阀门位置 4. 流量低于额定值60%时停机。', 'manual', 'Cooler'),
    ('轴承磨损故障案例', '某工厂CNC-A01设备在2025年3月出现振动值从0.15mm/s逐渐升至0.85mm/s，伴随温度从45°C升至62°C。经诊断为轴承磨损，更换主轴轴承后恢复正常。关键教训：应建立振动趋势监控，在振动值达到0.5mm/s时预警。', 'case', 'CNC'),
    ('液压泄漏故障案例', '某工厂Press-B01设备在运行中压力从25MPa骤降至15MPa，经检查为液压管路接头松动导致泄漏。紧固接头并更换密封圈后恢复。关键教训：应定期检查液压管路接头，安装压力突变检测。', 'case', 'Press')
ON CONFLICT DO NOTHING;
