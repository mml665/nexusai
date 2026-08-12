"""
Agent 3: 根因分析引擎（RAG + LLM）

流程：
1. 收到异常事件 → 构造检索查询
2. 混合检索：pgvector 向量相似度 + PostgreSQL 全文检索 → RRF 融合
3. 将异常数据 + 检索到的知识库文档 → 构造 LLM Prompt
4. LLM 生成诊断报告 + 维保建议 + 紧急程度
5. 写入 diagnosis_reports 表 + 发布 diagnosis_complete 事件

无 API Key 时降级为规则模板生成（保证系统可演示）。
"""

import json
import os
import httpx
import asyncpg
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass

from common.config import config


# ── 设备类型映射（用于知识库过滤） ─────────────────────────────
DEVICE_TYPE_MAP = {
    "CNC-A01": "CNC", "CNC-A02": "CNC",
    "ROBOT-A01": "Robot", "ROBOT-C01": "Robot",
    "PRESS-B01": "Press", "PRESS-B02": "Press",
    "CONV-B01": "Conveyor",
    "OVEN-C01": "Oven",
    "COOLER-C01": "Cooler",
}

# 异常类型中文映射
ANOMALY_TYPE_CN = {
    "threshold": "阈值超限",
    "sigma": "统计偏离",
    "trend": "趋势异常",
    "rate": "突变检测",
}

URGENCY_MAP = {
    "critical": "紧急",
    "warning": "一般",
    "info": "低",
}


@dataclass
class DiagnosisResult:
    """诊断结果"""
    device_id: str
    anomaly_type: str
    sensor_data: dict
    diagnosis: str
    recommendation: str
    urgency: str
    rag_sources: list[dict]
    created_at: str


async def init_knowledge_base_embeddings(pool) -> int:
    """
    启动时为知识库中 embedding 为空的记录生成向量。
    返回更新的行数。
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, title, content FROM knowledge_base WHERE embedding IS NULL"
        )
    if not rows:
        return 0

    updated = 0
    for row in rows:
        text = f"{row['title']}\n{row['content']}"
        embedding = await _get_embedding(text)
        if not embedding:
            continue
        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE knowledge_base SET embedding = $1::vector WHERE id = $2",
                embedding_str,
                row["id"],
            )
        updated += 1
    return updated


async def _get_embedding(text: str) -> Optional[list[float]]:
    """调用 OpenAI Embeddings API 获取文本向量"""
    api_key = config.OPENAI_API_KEY
    if not api_key:
        return None

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # 兼容 OpenAI 和其他兼容 API
            base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
            resp = await client.post(
                f"{base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
                    "input": text,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["data"][0]["embedding"]
    except Exception as e:
        print(f"[Diagnosis] Embedding API error: {e}")
        return None


async def _hybrid_retrieve(
    pool: asyncpg.Pool,
    query_text: str,
    device_type: Optional[str],
    top_k: int = 5,
) -> list[dict]:
    """
    混合检索：向量相似度 + 全文检索 → RRF 融合

    Returns:
        [{"title": ..., "content": ..., "category": ..., "score": ...}, ...]
    """
    embedding = await _get_embedding(query_text)
    sources: list[dict] = []

    async with pool.acquire() as conn:
        # ── 向量检索（pgvector cosine distance） ──
        vector_results = []
        if embedding:
            embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
            try:
                rows = await conn.fetch(
                    """
                    SELECT id, title, content, category, device_type,
                           1 - (embedding <=> $1::vector) AS similarity
                    FROM knowledge_base
                    WHERE ($2::text IS NULL OR device_type = $2)
                    ORDER BY embedding <=> $1::vector
                    LIMIT $3
                    """,
                    embedding_str,
                    device_type,
                    top_k,
                )
                for i, row in enumerate(rows):
                    vector_results.append({
                        "id": row["id"],
                        "title": row["title"],
                        "content": row["content"],
                        "category": row["category"],
                        "device_type": row["device_type"],
                        "_rank": i + 1,
                        "_similarity": float(row["similarity"]) if row["similarity"] else 0,
                    })
            except Exception as e:
                print(f"[Diagnosis] Vector search error: {e}")

        # ── 全文检索（PostgreSQL ts_vector） ──
        fts_results = []
        try:
            # 用简单的 ILIKE 做全文检索（比 ts_vector 更兼容）
            keywords = query_text.replace("，", " ").replace("。", " ").split()
            if keywords:
                conditions = " AND ".join(
                    [f"(content ILIKE '%' || ${i+2} || '%' OR title ILIKE '%' || ${i+2} || '%')"
                     for i in range(len(keywords))]
                )
                params = [device_type] + keywords + [top_k]
                rows = await conn.fetch(
                    f"""
                    SELECT id, title, content, category, device_type
                    FROM knowledge_base
                    WHERE ($1::text IS NULL OR device_type = $1)
                      AND ({conditions})
                    LIMIT ${len(keywords) + 2}
                    """,
                    *params,
                )
                for i, row in enumerate(rows):
                    fts_results.append({
                        "id": row["id"],
                        "title": row["title"],
                        "content": row["content"],
                        "category": row["category"],
                        "device_type": row["device_type"],
                        "_rank": i + 1,
                    })
        except Exception as e:
            print(f"[Diagnosis] FTS search error: {e}")

        # ── 如果两种检索都无结果，返回全部（按设备类型过滤） ──
        if not vector_results and not fts_results:
            try:
                rows = await conn.fetch(
                    """
                    SELECT id, title, content, category, device_type
                    FROM knowledge_base
                    WHERE ($1::text IS NULL OR device_type = $1)
                    LIMIT $2
                    """,
                    device_type,
                    top_k,
                )
                for i, row in enumerate(rows):
                    vector_results.append({
                        "id": row["id"],
                        "title": row["title"],
                        "content": row["content"],
                        "category": row["category"],
                        "device_type": row["device_type"],
                        "_rank": i + 1,
                        "_similarity": 0.0,
                    })
            except Exception as e:
                print(f"[Diagnosis] Fallback search error: {e}")

    # ── RRF (Reciprocal Rank Fusion) 融合 ──
    rrf_k = 60
    rrf_scores: dict[int, dict] = {}

    for doc in vector_results:
        doc_id = doc["id"]
        rrf_scores[doc_id] = {**doc}
        rrf_scores[doc_id]["score"] = 1.0 / (rrf_k + doc["_rank"])
        rrf_scores[doc_id]["source"] = "vector"

    for doc in fts_results:
        doc_id = doc["id"]
        if doc_id in rrf_scores:
            rrf_scores[doc_id]["score"] += 1.0 / (rrf_k + doc["_rank"])
            rrf_scores[doc_id]["source"] = "hybrid"
        else:
            rrf_scores[doc_id] = {**doc}
            rrf_scores[doc_id]["score"] = 1.0 / (rrf_k + doc["_rank"])
            rrf_scores[doc_id]["source"] = "fts"

    # 按 RRF 分数排序，取 top_k
    sorted_docs = sorted(rrf_scores.values(), key=lambda x: x["score"], reverse=True)[:top_k]

    for doc in sorted_docs:
        doc.pop("_rank", None)
        doc.pop("_similarity", None)
        doc["score"] = round(doc["score"], 4)
        sources.append(doc)

    return sources


def _build_diagnosis_prompt(
    device_id: str,
    device_type: str,
    anomaly_events: list[dict],
    sensor_data: dict,
    rag_sources: list[dict],
) -> str:
    """构造 LLM 诊断 Prompt"""

    anomalies_text = "\n".join(
        f"  - {ev['anomaly_type']}: {ev['message']} (severity={ev['severity']})"
        for ev in anomaly_events
    )

    sensors_text = "\n".join(
        f"  - {k}: {v:.2f}"
        for k, v in sensor_data.items()
    )

    knowledge_text = "\n\n".join(
        f"[文档{i+1}] {doc['title']}\n{doc['content']}"
        for i, doc in enumerate(rag_sources)
    ) if rag_sources else "（未检索到相关文档）"

    prompt = f"""你是一名工业设备故障诊断专家。请根据以下信息分析设备异常的根因，并给出诊断报告。

## 设备信息
- 设备ID: {device_id}
- 设备类型: {device_type}

## 当前传感器读数
{sensors_text}

## 检测到的异常
{anomalies_text}

## 知识库参考文档
{knowledge_text}

## 请输出（JSON格式）
{{
  "diagnosis": "根因分析（详细说明可能的故障原因和机理）",
  "recommendation": "维保建议（具体操作步骤）",
  "urgency": "紧急程度: critical(需立即停机) / warning(需尽快处理) / info(可观察)"
}}

注意：urgency 字段必须使用英文值 critical / warning / info 之一，不要用中文。

请基于知识库文档和异常数据给出专业、具体的分析。只输出 JSON，不要输出其他内容。"""

    return prompt


def _rule_based_diagnosis(
    device_id: str,
    device_type: str,
    anomaly_events: list[dict],
    sensor_data: dict,
    rag_sources: list[dict],
) -> DiagnosisResult:
    """
    规则模板生成诊断报告（无 LLM API Key 时的降级方案）
    """
    # 找最严重的异常
    critical_events = [e for e in anomaly_events if e["severity"] == "critical"]
    worst = critical_events[0] if critical_events else (anomaly_events[0] if anomaly_events else None)

    if worst is None:
        urgency = "info"
    elif worst["severity"] == "critical":
        urgency = "critical"
    else:
        urgency = "warning"

    # 根据传感器类型和异常类型生成诊断
    sensor = worst["sensor_type"] if worst else "unknown"
    anomaly_type = worst["anomaly_type"] if worst else "unknown"

    diagnosis_parts = []
    recommendation_parts = []

    # 匹配知识库
    relevant_kb = [s for s in rag_sources if sensor in s.get("content", "").lower() or sensor.replace("_", "") in s.get("content", "").lower()]

    if sensor in ("vibration",) and anomaly_type in ("threshold", "trend"):
        diagnosis_parts.append(f"设备{device_id}振动值异常，疑似主轴轴承磨损。振动值{sensor_data.get('vibration', 0):.2f}mm/s已超出安全范围。")
        recommendation_parts.append("1. 检查振动频谱，确认磨损频率\n2. 对比基线数据评估劣化程度\n3. 振动超0.8mm/s需立即停机更换轴承")
    elif sensor in ("temperature",) and anomaly_type in ("threshold", "trend", "rate"):
        diagnosis_parts.append(f"设备{device_id}温度异常，当前{sensor_data.get('temperature', 0):.1f}°C。可能原因：冷却系统故障、负载过大或环境温度过高。")
        recommendation_parts.append("1. 检查冷却液液位和循环\n2. 降低进给速度/负载\n3. 温度超85°C必须停机冷却")
    elif sensor in ("hydraulic_pressure", "pressure") and anomaly_type in ("threshold", "rate"):
        diagnosis_parts.append(f"设备{device_id}压力异常，当前{sensor_data.get(sensor, 0):.1f}。疑似液压系统泄漏或密封件损坏。")
        recommendation_parts.append("1. 检查液压管路接头\n2. 检查密封件状态\n3. 压力低于额定70%时停机检修")
    elif sensor == "current" and anomaly_type in ("threshold", "rate"):
        diagnosis_parts.append(f"设备{device_id}电流异常，当前{sensor_data.get('current', 0):.1f}A。可能电机过载或短路。")
        recommendation_parts.append("1. 检查负载情况\n2. 检查电机绝缘\n3. 电流超额定120%时停机")
    elif sensor == "position_accuracy":
        diagnosis_parts.append(f"设备{device_id}位置精度异常，当前{sensor_data.get('position_accuracy', 0):.3f}mm。疑似编码器漂移或机械松动。")
        recommendation_parts.append("1. 运行自检程序\n2. 对比标准位置校准编码器\n3. 紧固机械连接")
    elif sensor == "flow_rate":
        diagnosis_parts.append(f"设备{device_id}流量异常，当前{sensor_data.get('flow_rate', 0):.1f}L/min。可能管路堵塞或泵故障。")
        recommendation_parts.append("1. 检查过滤器\n2. 检查泵运行状态\n3. 流量低于60%额定值时停机")
    else:
        diagnosis_parts.append(f"设备{device_id}的{sensor}传感器检测到{ANOMALY_TYPE_CN.get(anomaly_type, anomaly_type)}异常。")
        recommendation_parts.append("1. 持续监控该参数趋势\n2. 安排巡检确认设备状态\n3. 如持续恶化则停机检查")

    # 附加知识库引用
    if relevant_kb:
        kb = relevant_kb[0]
        diagnosis_parts.append(f"\n参考文档《{kb['title']}》: {kb['content'][:150]}...")

    return DiagnosisResult(
        device_id=device_id,
        anomaly_type=anomaly_type,
        sensor_data=sensor_data,
        diagnosis="\n".join(diagnosis_parts),
        recommendation="\n".join(recommendation_parts),
        urgency=urgency,
        rag_sources=rag_sources,
        created_at=datetime.now(timezone.utc).isoformat(),
        llm_used=False,
    )


async def _llm_diagnosis(
    prompt: str,
    device_id: str,
    anomaly_type: str,
    sensor_data: dict,
    rag_sources: list[dict],
) -> Optional[DiagnosisResult]:
    """调用 LLM 生成诊断报告"""
    api_key = config.OPENAI_API_KEY
    if not api_key:
        return None

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": config.LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": "你是工业设备故障诊断专家，请以JSON格式输出诊断结果。"},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.3,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]

            # 解析 JSON（兼容 markdown code block）
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            result = json.loads(content)

            return DiagnosisResult(
                device_id=device_id,
                anomaly_type=anomaly_type,
                sensor_data=sensor_data,
                diagnosis=result.get("diagnosis", "LLM 未返回诊断内容"),
                recommendation=result.get("recommendation", "LLM 未返回维保建议"),
                urgency=result.get("urgency", "warning"),
                rag_sources=rag_sources,
                created_at=datetime.now(timezone.utc).isoformat(),
                llm_used=True,
            )
    except Exception as e:
        print(f"[Diagnosis] LLM API error: {e}")
        return None


async def run_diagnosis(
    pool: asyncpg.Pool,
    device_id: str,
    anomaly_events: list[dict],
    sensor_data: dict,
) -> DiagnosisResult:
    """
    执行完整的根因分析流程

    1. 构造检索查询
    2. 混合检索知识库
    3. LLM 诊断（降级为规则模板）
    4. 写入 diagnosis_reports 表
    5. 返回结果（供调用方发布 Pub/Sub 事件）
    """
    device_type = DEVICE_TYPE_MAP.get(device_id)

    # ── 构造检索查询 ──
    anomaly_summary = " ".join(
        f"{ev['sensor_type']} {ANOMALY_TYPE_CN.get(ev['anomaly_type'], ev['anomaly_type'])}"
        for ev in anomaly_events
    )
    query_text = f"{device_id} {device_type or ''} {anomaly_summary} 故障 诊断 维护"

    # ── 混合检索 ──
    rag_sources = await _hybrid_retrieve(pool, query_text, device_type, top_k=5)

    # ── LLM 诊断（有 API Key 时） ──
    result: Optional[DiagnosisResult] = None
    if config.OPENAI_API_KEY:
        prompt = _build_diagnosis_prompt(device_id, device_type or "未知", anomaly_events, sensor_data, rag_sources)
        anomaly_type = anomaly_events[0]["anomaly_type"] if anomaly_events else "unknown"
        result = await _llm_diagnosis(prompt, device_id, anomaly_type, sensor_data, rag_sources)

    # ── 降级：规则模板 ──
    if result is None:
        anomaly_type = anomaly_events[0]["anomaly_type"] if anomaly_events else "unknown"
        result = _rule_based_diagnosis(device_id, device_type or "未知", anomaly_events, sensor_data, rag_sources)

    # ── 写入数据库 ──
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO diagnosis_reports
                (device_id, anomaly_type, sensor_data, diagnosis, recommendation, urgency, rag_sources)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            device_id,
            result.anomaly_type,
            json.dumps(sensor_data),
            result.diagnosis,
            result.recommendation,
            result.urgency,
            json.dumps(result.rag_sources, ensure_ascii=False),
        )

    return result
