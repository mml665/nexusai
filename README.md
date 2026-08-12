# NexusAI - 智能工厂实时运营平台

> Smart Factory Real-time Operations Platform — 8 microservices, 5 heterogeneous data stores, 3 AI agents

## 架构概览

```
工厂模拟器 (9设备 × 4传感器, 1秒/次)
       ↓ HTTP POST
  IoT Collector (:8001)
       ↓ Redis Streams
  ┌────────────────────────────────┐
  │  Stream Processor (:8002)      │  → TimescaleDB (时序数据)
  │  - 实时 OEE 计算                │  → Redis (实时状态缓存)
  │  - 滑动窗口维护                 │
  └────────────────────────────────┘
       ↓ Redis Streams (消费者组)
  ┌────────────────────────────────┐
  │  AI Engine (:8004)             │
  │  - 异常检测 Agent (<100ms)      │  → Redis Pub/Sub (异常事件)
  │  - 预测维护 Agent (每5分钟)      │  → TimescaleDB (预测结果)
  │  - 根因分析 Agent (RAG + LLM)   │  → TimescaleDB (诊断报告)
  └────────────────────────────────┘
       ↓ Redis Pub/Sub
  ┌────────────────────────────────┐
  │  Smart Alert (:8006)           │
  │  - 告警分级 / 去重 / 升级        │
  └────────────────────────────────┘
       ↓
  Analytics API (:8005)  ←  Asset Manager (:8007)
  - REST + WebSocket       - 设备台账 / 工单 / RBAC
       ↓
  Gateway (:8000)  ←  Observability (:8008)
  - API 路由 + WS 代理    - 服务健康监控
       ↓
  Nginx (:80) → Frontend (React 实时大屏)
```

## 数据存储

| 存储 | 用途 |
|------|------|
| **TimescaleDB** (PostgreSQL 16) | 传感器时序数据、OEE 指标、业务表 |
| **pgvector** | 设备手册向量检索 (RAG) |
| **Redis** | Streams (事件管道) + Pub/Sub (通知) + 缓存 |
| **Elasticsearch** | 日志聚合、全文搜索 |

## 3 个 AI Agent

### 1. 异常检测 Agent
- 4 种检测策略：静态阈值 / 3σ 动态基线 / 趋势检测 / 变化率检测
- 纯内存计算，响应 < 100ms，无需 LLM
- 滑动窗口 60 个数据点

### 2. 预测维护 Agent
- 线性回归趋势分析 + RUL (剩余寿命) 预测
- 加权健康度评分 (0-100)
- 每 5 分钟自动运行

### 3. 根因分析 Agent (RAG)
- 混合检索：pgvector 向量相似度 + ILIKE 全文搜索 + RRF 融合
- LLM 生成诊断报告 (无 API Key 时降级为规则模板)
- 自动关联异常事件与设备知识库

## 快速启动

```bash
# 克隆
git clone https://github.com/mml665/nexusai.git
cd nexusai

# (可选) 配置 LLM — 不配也能运行，诊断降级为规则模板
export OPENAI_API_KEY=sk-xxx

# 一键启动 (12 个容器)
docker compose up --build

# 访问 http://localhost
```

## 工厂模拟器

3 条产线，9 台设备，每台 4 个传感器，每秒推送数据：

| 产线 | 设备 |
|------|------|
| A (精密加工) | CNC-A01, CNC-A02, ROBOT-A01 |
| B (成型装配) | PRESS-B01, PRESS-B02, CONV-B01 |
| C (热处理) | OVEN-C01, COOLER-C01, ROBOT-C01 |

### 故障注入

5 种故障类型：
- **轴承磨损** (bearing_wear) — 振动渐增
- **过热** (overheating) — 温度突升
- **校准漂移** (calibration_drift) — 压力偏移
- **液压泄漏** (hydraulic_leak) — 压力骤降
- **电气故障** (electrical_fault) — 电流突升

在前端「故障注入」页面注入故障，即可观察完整的 **检测 → 诊断 → 告警 → 维护建议** 全自动流程。

## 技术栈

- **后端**: Python 3.11 / FastAPI / asyncpg / redis-py
- **前端**: React 18 / TypeScript / Vite / ECharts
- **基础设施**: Docker Compose / TimescaleDB / Redis / Elasticsearch / Nginx
- **AI**: RAG (pgvector) / LLM (OpenAI compatible)

## 项目结构

```
nexusai/
├── docker-compose.yml
├── scripts/init_db.sql
├── docs/design.md
├── nginx/nginx.conf
├── simulator/              # 工厂模拟器
│   ├── factory.py
│   ├── sensors.py
│   ├── faults.py
│   └── main.py
├── services/
│   ├── common/             # 共享模块
│   ├── gateway/            # API 网关 (:8000)
│   ├── iot_collector/      # 数据接入 (:8001)
│   ├── stream_processor/   # 流处理 (:8002)
│   ├── ai_engine/          # AI 引擎 (:8004)
│   │   └── agents/
│   │       ├── anomaly.py
│   │       ├── maintenance.py
│   │       └── diagnosis.py
│   ├── analytics/          # 分析 API (:8005)
│   ├── alert/              # 告警引擎 (:8006)
│   ├── asset_manager/      # 资产管理 (:8007)
│   └── observability/      # 可观测性 (:8008)
└── frontend/               # React 实时大屏
```

## License

MIT
