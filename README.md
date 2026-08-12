# NexusAI - 智能工厂实时运营平台

> Smart Factory Real-time Operations Platform — 8 microservices, 5 heterogeneous data stores, 3 AI agents, enterprise-grade security & observability

## 架构概览

```
工厂模拟器 (9设备 × 4传感器, 1秒/次)
       ↓ HTTP POST
  IoT Collector (:8001)
       ↓ Redis Streams
  ┌────────────────────────────────┐
  │  Stream Processor (:8002)      │  → TimescaleDB (时序数据)
  │  - 实时 OEE 计算                │  → Redis (实时状态缓存)
  │  - 滑动窗口维护                 │  → DLQ (失败消息不丢失)
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
  - JWT 认证 + 路由代理     - 服务健康监控
  - 限流 + 熔断 + Prometheus  - /metrics 指标暴露
       ↓
  Nginx (:80) → Frontend (React 实时大屏)

  ┌────────────────────────────────┐
  │  可观测性基础设施                │
  │  Prometheus (:9090) — 指标抓取  │
  │  Grafana (:3001) — 仪表盘       │
  └────────────────────────────────┘
```

## 企业级工程实践

### 安全加固

| 特性 | 实现 |
|------|------|
| **JWT 认证** | 手写 HMAC-SHA256 签名，零外部 JWT 库依赖 |
| **RBAC 权限控制** | 三级角色 (admin / operator / viewer)，FastAPI 依赖注入 |
| **密码哈希** | bcrypt (cost=12)，数据库层 pgcrypto crypt() 验证 |
| **CORS 白名单** | 从环境变量读取，不再使用 `*` 通配符 |
| **SQL 注入修复** | 参数化查询替代字符串拼接 (`INTERVAL` 漏洞已修复) |
| **统一错误响应** | `{"error": {"code", "message", "details"}, "service", "path"}` |
| **死信队列** | 消费失败的消息自动进入 DLQ，不丢失不阻塞 |

### 弹性设计

| 模式 | 实现 |
|------|------|
| **Circuit Breaker** | CLOSED → OPEN (5次失败) → HALF_OPEN (30s超时) → CLOSED/OPEN |
| **滑动窗口限流** | 全局 200 req/min + 登录 10 req/min，按客户端 IP 隔离 |
| **指数退避重试** | asyncio 实现，带 jitter 抖动，可配置重试异常类型 |
| **熔断器隔离** | 每个下游服务独立熔断器，互不影响 |

### 可观测性

| 组件 | 实现 |
|------|------|
| **Prometheus 指标** | 手写文本格式，零 prometheus_client 依赖 |
| **Grafana 仪表盘** | 自动 provisioning，6 面板 (请求率/P95延迟/传感器/异常/LLM/错误率) |
| **业务指标** | sensor_readings_processed, anomalies_detected_total, llm_calls_total |
| **健康检查** | 所有 8 个微服务 + 3 个基础设施组件 Docker healthcheck |

### 测试 & CI/CD

| 特性 | 实现 |
|------|------|
| **单元测试** | 36 个 pytest 测试 (认证 / 弹性 / 异常检测 / API) |
| **Lint** | ruff (line-length=120, target=py312) |
| **CI/CD** | GitHub Actions: lint → test → build → frontend build |
| **数据库迁移** | Alembic，baseline migration 对应 init_db.sql |

## 数据存储

| 存储 | 用途 |
|------|------|
| **TimescaleDB** (PostgreSQL 16) | 传感器时序数据、OEE 指标、业务表 |
| **pgvector** | 设备手册向量检索 (RAG) |
| **pgcrypto** | 数据库层密码哈希验证 (crypt + gen_salt) |
| **Redis** | Streams (事件管道) + Pub/Sub (通知) + 缓存 + DLQ |
| **Elasticsearch** | 日志聚合、全文搜索 |
| **Prometheus** | 时序指标存储 (7天保留) |

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

# 一键启动 (16 个容器)
docker compose up --build

# 访问
# http://localhost       — 前端大屏 (需登录)
# http://localhost:3001  — Grafana (admin/admin123)
# http://localhost:9090  — Prometheus
```

### 演示账号

| 用户名 | 密码 | 角色 | 权限 |
|--------|------|------|------|
| admin | admin123 | admin | 全部功能 + 用户管理 + 熔断器状态 |
| operator | operator123 | operator | 设备管理 + 工单 + 故障注入 |
| viewer | viewer123 | viewer | 只读查看 |

### 开发命令

```bash
make up          # 启动所有服务
make down        # 停止
make rebuild     # 重建所有镜像
make test        # 运行单元测试
make test-all    # 运行全部测试 (含覆盖率)
make lint        # 代码检查
make lint-fix    # 自动修复
make logs        # 查看所有服务日志
make ps          # 查看容器状态
make shell-gateway  # 进入 Gateway 容器
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

- **后端**: Python 3.12 / FastAPI / asyncpg / redis-py / bcrypt
- **前端**: React 18 / TypeScript / Vite / ECharts
- **基础设施**: Docker Compose / TimescaleDB / Redis / Elasticsearch / Nginx
- **可观测性**: Prometheus / Grafana
- **AI**: RAG (pgvector) / LLM (OpenAI compatible)
- **测试**: pytest / pytest-asyncio / ruff / mypy
- **CI/CD**: GitHub Actions
- **数据库迁移**: Alembic

## 项目结构

```
nexusai/
├── docker-compose.yml          # 16 容器编排
├── Makefile                    # 开发命令快捷方式
├── pyproject.toml              # pytest / ruff / mypy 配置
├── .github/workflows/ci.yml    # GitHub Actions CI/CD
├── .env.example                # 环境变量文档
├── alembic/                    # 数据库迁移
│   └── versions/001_initial_schema.py
├── scripts/init_db.sql         # 数据库初始化 (pgcrypto + 种子数据)
├── prometheus/prometheus.yml   # Prometheus 抓取配置
├── grafana/                    # Grafana 仪表盘
│   ├── provisioning/           # 自动配置数据源 + 仪表盘
│   └── dashboards/             # NexusAI 概览面板
├── nginx/nginx.conf
├── simulator/                  # 工厂模拟器
├── services/
│   ├── common/                 # 共享模块
│   │   ├── auth.py             # JWT + bcrypt + RBAC
│   │   ├── config.py           # 统一配置
│   │   ├── resilience.py       # 熔断 + 限流 + 重试
│   │   ├── metrics.py          # Prometheus 指标
│   │   └── errors.py           # 统一错误处理
│   ├── gateway/                # API 网关 (:8000)
│   ├── iot_collector/          # 数据接入 (:8001)
│   ├── stream_processor/       # 流处理 (:8002)
│   ├── ai_engine/              # AI 引擎 (:8004)
│   │   └── agents/
│   │       ├── anomaly.py
│   │       ├── maintenance.py
│   │       └── diagnosis.py
│   ├── analytics/              # 分析 API (:8005)
│   ├── alert/                  # 告警引擎 (:8006)
│   ├── asset_manager/          # 资产管理 (:8007)
│   └── observability/          # 可观测性 (:8008)
├── tests/                      # 测试套件 (36 tests)
│   ├── conftest.py
│   ├── test_auth.py            # JWT + 密码哈希 + 公共路径
│   ├── test_resilience.py      # 熔断 + 限流 + 重试
│   ├── test_anomaly.py         # 异常检测算法
│   └── test_api.py             # API 集成测试
└── frontend/                   # React 实时大屏
    └── src/
        ├── pages/Login.tsx     # 登录页
        ├── api.ts              # Token 管理 + API 封装
        └── App.tsx             # 认证状态 + 角色路由
```

## License

MIT
