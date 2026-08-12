# NexusAI - 智能工厂实时运营平台设计文档

## 1. 系统概述

NexusAI 是一个基于微服务架构的工业 IoT 智能运营平台，模拟一个真实工厂的实时运行状况。系统通过工厂模拟器持续生成传感器时序数据、设备状态事件和生产订单事件，经过消息队列分发到 8 个微服务并行处理，AI Engine 对数据进行实时异常检测、预测性维护和根因分析，前端通过 WebSocket 实时展示工厂运营大屏。

### 核心特征
- **系统始终在运行**：docker compose up 后，模拟器持续推送数据，8 个服务并行处理，前端大屏实时跳动
- **AI 是组件不是全部**：AI Engine 只是 8 个服务之一，系统还有数据管道、流处理、告警、设备管理等完整业务逻辑
- **5 种异构数据存储**：TimescaleDB（时序）、PostgreSQL（业务）、Elasticsearch（日志）、Redis（实时状态）、pgvector（向量）
- **故障注入演示**：一键注入设备故障，看 AI 检测→诊断→告警→维保建议全流程自动完成

## 2. 技术栈

| 层 | 技术选型 |
|---|---|
| 后端框架 | Python 3.12 + FastAPI |
| 消息队列 | Redis Streams + Redis Pub/Sub |
| 异步任务 | Celery + Redis |
| 时序数据库 | TimescaleDB (PostgreSQL 扩展) |
| 关系数据库 | PostgreSQL |
| 搜索引擎 | Elasticsearch |
| 缓存 | Redis |
| 向量数据库 | pgvector (PostgreSQL 扩展) |
| 前端 | React 18 + TypeScript + Vite + ECharts + WebSocket |
| 反向代理 | Nginx |
| 容器化 | Docker + Docker Compose |

## 3. 系统架构

```
工厂模拟器（持续推送）
    │
    ▼
Redis Streams（事件管道）
    │
    ▼
┌─────────────────────────────────────────────────┐
│              8 个微服务并行处理                    │
│                                                   │
│  Gateway → IoT Collector → Stream Processor       │
│                                       ↓            │
│  AI Engine ← Celery异步 ← 数据流                  │
│       ↓                                           │
│  Smart Alert → Analytics API → WebSocket推送      │
│                                                   │
│  Asset Manager    Observability                   │
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│         5 种异构数据存储                           │
│  TimescaleDB | PostgreSQL | Elasticsearch         │
│  Redis | pgvector                                 │
└─────────────────────────────────────────────────┘
    │
    ▼
前端实时大屏（WebSocket）
```

## 4. 工厂模拟器设计

### 4.1 工厂模型

```
工厂
├── 产线 A（3台设备）
│   ├── CNC-A01（温度/振动/主轴转速/切削力）
│   ├── CNC-A02（温度/振动/主轴转速/切削力）
│   └── Robot-A01（温度/振动/电流/位置精度）
├── 产线 B（3台设备）
│   ├── Press-B01（温度/液压/压力/行程）
│   ├── Press-B02（温度/液压/压力/行程）
│   └── Conveyor-B01（温度/转速/电流/速度）
└── 产线 C（3台设备）
    ├── Oven-C01（温度/燃气/压力/门状态）
    ├── Cooler-C01（温度/流量/压力/阀门）
    └── Robot-C01（温度/振动/电流/位置精度）
```

### 4.2 传感器数据生成

每台设备 4 个传感器，每秒生成一条数据：

```json
{
  "device_id": "CNC-A01",
  "timestamp": "2026-08-12T11:30:00Z",
  "sensors": {
    "temperature": 45.2,      // 正常 40-50°C
    "vibration": 0.15,        // 正常 0.1-0.3 mm/s
    "spindle_speed": 3000,    // 正常 2800-3200 RPM
    "cutting_force": 120      // 正常 100-150 N
  },
  "status": "running"         // running / idle / maintenance / fault
}
```

### 4.3 故障注入

| 故障类型 | 影响传感器 | 表现 | 触发方式 |
|---|---|---|---|
| 轴承磨损 | 振动渐增 | 振动从 0.15 缓慢升到 0.8+ | API 调用 |
| 过热 | 温度突增 | 温度从 45° 升到 85°+ | API 调用 |
| 校准漂移 | 转速偏差 | 转速偏离设定值 | API 调用 |
| 液压泄漏 | 压力骤降 | 压力从正常值骤降 | API 调用 |
| 电气故障 | 电流突增 | 电流异常飙升 | API 调用 |

### 4.4 生产事件

- 工单开工/完工
- 质检通过/不合格
- 设备启停
- 维保开始/完成

## 5. 微服务详细设计

### 5.1 Gateway（API 网关）

**端口**：8000

**职责**：
- JWT 认证 + 设备 Token 认证
- 车间级数据隔离
- API 路由转发
- 请求限流

**核心路由**：
```
/api/v1/sensors/*        → iot_collector:8001
/api/v1/metrics/*        → analytics:8005
/api/v1/alerts/*         → alert:8006
/api/v1/devices/*        → asset_manager:8007
/api/v1/ai/*             → ai_engine:8004
/api/v1/faults/inject    → simulator:8009
/ws                      → analytics:8005 (WebSocket)
```

### 5.2 IoT Collector（数据接入）

**端口**：8001

**职责**：
- 接收模拟器推送的传感器数据
- 数据校验（范围检查、时间戳校验）
- 写入 Redis Streams 供下游消费
- 设备注册管理

**数据流**：
```
模拟器 → POST /api/v1/sensors/data → 校验 → Redis Streams(sensor_data)
```

### 5.3 Stream Processor（流处理引擎）

**端口**：8002（管理接口）

**职责**：
- 从 Redis Streams 消费传感器数据
- 实时计算 OEE（设备综合效率）
- 滑动窗口聚合（1分钟/5分钟/1小时）
- 产量和良率统计
- 写入 TimescaleDB

**OEE 计算**：
```
OEE = 可用率 × 性能率 × 质量率
可用率 = 实际运行时间 / 计划运行时间
性能率 = 实际产量 / 理论产量
质量率 = 合格品 / 总产量
```

**消费组**：
- `stream_processor`: 消费 `sensor_data` 流
- 写入 TimescaleDB 的 `sensor_readings` 和 `oee_metrics` 表

### 5.4 AI Engine（AI 引擎）

**端口**：8004

**3 个 Agent 详细设计**：

#### Agent 1: 异常检测（不用 LLM，规则+统计）
- **输入**：实时传感器数据流
- **方法**：
  - 静态阈值检测（温度 > 80°C = 异常）
  - 动态基线检测（3σ 偏离）
  - 趋势检测（连续 N 点单调递增/递减）
  - 变化率检测（1秒内变化超过阈值）
- **输出**：异常事件 → Redis Pub/Sub `anomaly_detected`
- **延迟**：< 100ms

#### Agent 2: 预测维护（趋势分析）
- **输入**：历史传感器时序数据（从 TimescaleDB 查询）
- **方法**：
  - 线性回归趋势分析（振动趋势）
  - 剩余寿命预测（RUL）
  - 健康度评分（0-100）
- **触发**：每 5 分钟定时执行，或异常事件触发
- **输出**：维护建议 → Celery 异步 → PostgreSQL `maintenance_predictions`

#### Agent 3: 根因分析（RAG + LLM）
- **输入**：异常事件 + 设备信息
- **方法**：
  - 用 RAG 从设备手册和故障案例库检索相关文档
  - LLM 结合异常数据和检索结果生成诊断报告
  - 给出维保建议和紧急程度
- **输出**：诊断报告 → PostgreSQL `diagnosis_reports` + Pub/Sub `diagnosis_complete`
- **复用**：现有 RAG 混合检索（向量+BM25+RRF+Rerank）直接迁移

### 5.5 Analytics API（分析查询）

**端口**：8005

**职责**：
- REST API 查询指标（OEE、产量、良率、设备状态）
- WebSocket 实时推送（传感器数据、告警、AI 诊断）
- NL2SQL 自然语言查询（复用 Tool Calling）
- 缓存层（Redis 缓存热点查询）

**WebSocket 频道**：
```
ws://localhost:8000/ws/sensors     # 实时传感器数据
ws://localhost:8000/ws/alerts      # 实时告警
ws://localhost:8000/ws/diagnosis   # AI诊断结果
ws://localhost:8000/ws/oee         # 实时OEE
```

### 5.6 Smart Alert（告警引擎）

**端口**：8006

**职责**：
- 订阅 `anomaly_detected` 事件
- 告警分级（critical / warning / info）
- 升级策略（未处理自动升级）
- 多渠道通知（WebSocket + 日志 + 可扩展邮件/短信）
- 告警去重和抑制

**告警状态机**：
```
triggered → acknowledged → processing → resolved
                                    ↘ false_alarm
```

### 5.7 Asset Manager（设备管理）

**端口**：8007

**职责**：
- 设备台账 CRUD
- 维保计划管理
- 工单管理
- RBAC 权限（admin / operator / viewer）
- 操作审计日志

**数据模型**：
- `devices`：设备信息
- `maintenance_plans`：维保计划
- `work_orders`：工单
- `users`：用户
- `audit_logs`：审计日志

### 5.8 Observability（可观测性）

**端口**：8008

**职责**：
- 服务健康检查
- 链路追踪（请求 ID 贯穿）
- 服务指标采集
- 系统状态面板

## 6. 数据模型

### 6.1 TimescaleDB（时序数据）

```sql
-- 传感器读数（超表）
CREATE TABLE sensor_readings (
    time        TIMESTAMPTZ NOT NULL,
    device_id   TEXT NOT NULL,
    sensor_type TEXT NOT NULL,  -- temperature/vibration/pressure/rpm
    value       DOUBLE PRECISION NOT NULL,
    status      TEXT DEFAULT 'normal'
);
SELECT create_hypertable('sensor_readings', 'time');

-- OEE 指标（超表）
CREATE TABLE oee_metrics (
    time         TIMESTAMPTZ NOT NULL,
    device_id    TEXT NOT NULL,
    availability DOUBLE PRECISION,
    performance  DOUBLE PRECISION,
    quality      DOUBLE PRECISION,
    oee          DOUBLE PRECISION,
    output_count INTEGER,
    defect_count INTEGER
);
SELECT create_hypertable('oee_metrics', 'time');
```

### 6.2 PostgreSQL（业务数据）

```sql
-- 设备台账
CREATE TABLE devices (
    id          SERIAL PRIMARY KEY,
    device_id   TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    line        TEXT NOT NULL,       -- A/B/C
    type        TEXT NOT NULL,       -- CNC/Press/Oven/Robot/Conveyor/Cooler
    sensors     JSONB NOT NULL,      -- ["temperature","vibration",...]
    status      TEXT DEFAULT 'running',
    installed_at DATE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 维保预测
CREATE TABLE maintenance_predictions (
    id              SERIAL PRIMARY KEY,
    device_id       TEXT NOT NULL,
    health_score    INTEGER NOT NULL,    -- 0-100
    predicted_rul   INTEGER,             -- 剩余寿命(小时)
    risk_level      TEXT NOT NULL,       -- low/medium/high/critical
    recommendation  TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 诊断报告
CREATE TABLE diagnosis_reports (
    id           SERIAL PRIMARY KEY,
    device_id    TEXT NOT NULL,
    anomaly_type TEXT NOT NULL,
    sensor_data  JSONB NOT NULL,
    diagnosis    TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    urgency      TEXT NOT NULL,       -- immediate/urgent/schedule
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- 告警
CREATE TABLE alerts (
    id          SERIAL PRIMARY KEY,
    device_id   TEXT NOT NULL,
    type        TEXT NOT NULL,        -- fault/quality/safety
    severity    TEXT NOT NULL,        -- critical/warning/info
    title       TEXT NOT NULL,
    description TEXT,
    status      TEXT DEFAULT 'triggered', -- triggered/acknowledged/resolved
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

-- 用户
CREATE TABLE users (
    id          SERIAL PRIMARY KEY,
    username    TEXT UNIQUE NOT NULL,
    password    TEXT NOT NULL,
    role        TEXT DEFAULT 'viewer', -- admin/operator/viewer
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 审计日志
CREATE TABLE audit_logs (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER,
    action      TEXT NOT NULL,
    resource    TEXT NOT NULL,
    detail      JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
```

### 6.3 pgvector（知识库）

```sql
-- 设备手册和故障案例（RAG知识库）
CREATE TABLE knowledge_base (
    id          SERIAL PRIMARY KEY,
    title       TEXT NOT NULL,
    content     TEXT NOT NULL,
    category    TEXT NOT NULL,        -- manual/case/solution
    device_type TEXT,
    embedding   vector(1024)
);
```

### 6.4 Elasticsearch（日志）

```json
// 设备日志索引
{
  "device_id": "CNC-A01",
  "timestamp": "2026-08-12T11:30:00Z",
  "level": "INFO",
  "event": "production_start",
  "message": "工单 #20260812-001 开始生产",
  "metadata": {}
}
```

## 7. 事件类型定义

| 事件 | 频道 | 生产者 | 消费者 |
|---|---|---|---|
| 传感器数据 | Redis Streams `sensor_data` | IoT Collector | Stream Processor |
| OEE 指标 | Redis Pub/Sub `oee_update` | Stream Processor | Analytics API |
| 异常检测 | Redis Pub/Sub `anomaly_detected` | AI Engine (Agent 1) | Smart Alert, AI Engine (Agent 3) |
| 维保预测 | Celery task | AI Engine (Agent 2) | Asset Manager |
| 诊断报告 | Redis Pub/Sub `diagnosis_complete` | AI Engine (Agent 3) | Analytics API, Smart Alert |
| 告警触发 | Redis Pub/Sub `alert_triggered` | Smart Alert | Analytics API |
| 设备状态变更 | Redis Pub/Sub `device_status` | IoT Collector | Analytics API |

## 8. 项目目录结构

```
nexusai/
├── docker-compose.yml
├── .env.example
├── nginx/
│   └── nginx.conf
├── simulator/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py              # FastAPI 服务 + 数据推送
│   ├── factory.py            # 工厂模型定义
│   ├── sensors.py            # 传感器数据生成
│   └── faults.py             # 故障注入逻辑
├── services/
│   ├── common/               # 共享模块
│   │   ├── __init__.py
│   │   ├── config.py         # 配置管理
│   │   ├── db.py             # PostgreSQL/TimescaleDB 连接
│   │   ├── redis_client.py   # Redis 连接
│   │   ├── es_client.py      # Elasticsearch 连接
│   │   └── events.py         # 事件类型常量
│   ├── gateway/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── main.py
│   ├── iot_collector/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── main.py
│   ├── stream_processor/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── main.py
│   │   └── oee.py
│   ├── ai_engine/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── main.py
│   │   └── agents/
│   │       ├── anomaly.py
│   │       ├── maintenance.py
│   │       └── diagnosis.py
│   ├── analytics/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── main.py
│   ├── alert/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── main.py
│   ├── asset_manager/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── main.py
│   └── observability/
│       ├── Dockerfile
│       ├── requirements.txt
│       └── main.py
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── Dockerfile
│   └── src/
│       ├── App.tsx
│       ├── main.tsx
│       ├── components/
│       │   ├── FactoryDashboard.tsx
│       │   ├── SensorChart.tsx
│       │   ├── AIDiagnosis.tsx
│       │   ├── AlertCenter.tsx
│       │   └── DeviceManager.tsx
│       └── api/
│           └── client.ts
├── scripts/
│   ├── init_db.sql           # 数据库初始化SQL
│   └── seed_knowledge.py     # 知识库初始化
└── docs/
    └── design.md
```

## 9. 分阶段实施计划

### 阶段 1：基础设施 + 模拟器（3天）
- Docker Compose 编排（5 个数据存储 + Nginx）
- 数据库初始化脚本（建表 + 知识库种子数据）
- 工厂模拟器（设备模型、传感器生成、故障注入）

### 阶段 2：核心服务（3天）
- Gateway（认证、路由、限流）
- IoT Collector（数据接入、校验、写 Stream）
- Stream Processor（OEE 计算、窗口聚合、写 TimescaleDB）

### 阶段 3：AI Engine + Alert（3天）
- 异常检测 Agent（规则引擎）
- 预测维护 Agent（趋势分析）
- 根因分析 Agent（RAG + LLM）
- Smart Alert（告警状态机、升级策略）

### 阶段 4：剩余服务 + 前端（3天）
- Analytics API（REST + WebSocket + NL2SQL）
- Asset Manager（设备台账、工单、RBAC）
- Observability（健康检查）
- React 前端实时大屏

### 阶段 5：联调 + 完善（2天）
- 端到端联调
- 故障注入完整流程验证
- Docker Compose 一键启动验证
- 文档完善

## 10. 简历项目描述

**NexusAI - 智能工厂实时运营平台**

基于微服务架构的工业 IoT 智能运营平台，通过工厂模拟器持续生成传感器时序数据，8 个微服务并行处理，AI 引擎实时进行异常检测、预测性维护和根因分析。

- 设计并实现 8 个微服务（Gateway/IoT Collector/Stream Processor/AI Engine/Analytics/Alert/Asset Manager/Observability），使用 FastAPI + Redis Streams + Celery 构建事件驱动架构
- 集成 5 种异构数据存储：TimescaleDB（传感器时序）、PostgreSQL（业务数据）、Elasticsearch（日志检索）、Redis（实时状态）、pgvector（RAG 向量检索）
- 实现 3 个 AI Agent：基于规则+统计的实时异常检测（<100ms）、基于趋势分析的设备剩余寿命预测、基于 RAG 混合检索（向量+BM25+RRF+Rerank）的故障根因分析
- 构建工厂模拟器模拟 3 条产线 9 台设备，支持 5 种故障注入（轴承磨损/过热/校准漂移/液压泄漏/电气故障）
- 使用 Docker Compose 编排全部服务，一键启动完整系统；前端 React + WebSocket 实时展示工厂运营大屏
