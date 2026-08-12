import { useState, useEffect } from "react";
import { api, useWebSocketStream, usePolling } from "../api";
import type { AlertData, DiagnosisData } from "../types";
import { SEVERITY_COLORS } from "../types";

export default function Alerts() {
  const { data: alertsData, loading } = usePolling(() => api.getAlerts(), 5000);
  const { data: alertStats } = usePolling(() => api.getAlertStats(), 10000);
  const diagnoses = useWebSocketStream<DiagnosisData>("diagnosis", 20);
  const { data: historyDiagnoses } = usePolling(() => api.getDiagnoses(15), 10000);
  const [filter, setFilter] = useState<string>("");

  const alerts = (alertsData?.data || []).filter(a => !filter || a.severity === filter);

  const handleAck = async (id: number) => {
    try { await api.acknowledgeAlert(id); } catch (e) { console.error(e); }
  };
  const handleResolve = async (id: number) => {
    try { await api.resolveAlert(id); } catch (e) { console.error(e); }
  };

  return (
    <div>
      <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 20, color: "#e0e6ed" }}>告警 & AI 诊断</h2>

      {/* 告警统计 */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 20 }}>
        {[
          { label: "活跃告警", value: alertStats?.active_count || 0, color: "#ef4444" },
          { label: "严重", value: alertStats?.by_severity_status?.critical_triggered || 0, color: "#ef4444" },
          { label: "警告", value: alertStats?.by_severity_status?.warning_triggered || 0, color: "#f59e0b" },
          { label: "已解决", value: alertStats?.by_severity_status?.critical_resolved + alertStats?.by_severity_status?.warning_resolved || 0, color: "#10b981" },
        ].map(card => (
          <div key={card.label} style={{ background: "#111827", borderRadius: 12, padding: 16, border: "1px solid #1f2937" }}>
            <div style={{ fontSize: 12, color: "#6b7280" }}>{card.label}</div>
            <div style={{ fontSize: 28, fontWeight: 700, color: card.color }}>{card.value}</div>
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        {/* 告警列表 */}
        <div style={{ background: "#111827", borderRadius: 12, padding: 20, border: "1px solid #1f2937" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
            <h3 style={{ fontSize: 14, color: "#9ca3af" }}>告警列表</h3>
            <div style={{ display: "flex", gap: 8 }}>
              {[{ v: "", l: "全部" }, { v: "critical", l: "严重" }, { v: "warning", l: "警告" }].map(f => (
                <button key={f.v} onClick={() => setFilter(f.v)}
                  style={{
                    padding: "4px 10px", borderRadius: 6, fontSize: 11, cursor: "pointer",
                    background: filter === f.v ? "rgba(59,130,246,0.2)" : "#1f2937",
                    border: "1px solid", borderColor: filter === f.v ? "#3b82f6" : "#374151",
                    color: filter === f.v ? "#3b82f6" : "#9ca3af",
                  }}>{f.l}</button>
              ))}
            </div>
          </div>
          <div style={{ maxHeight: 500, overflowY: "auto" }}>
            {loading ? <div style={{ color: "#4b5563", textAlign: "center", padding: 20 }}>加载中...</div> :
             alerts.length === 0 ? <div style={{ color: "#4b5563", textAlign: "center", padding: 20 }}>暂无告警</div> :
             alerts.map(alert => (
              <div key={alert.id} style={{
                padding: 12, marginBottom: 8, borderRadius: 8, background: "#0a0e1a",
                borderLeft: `3px solid ${SEVERITY_COLORS[alert.severity] || "#6b7280"}`,
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: SEVERITY_COLORS[alert.severity] }}>
                    [{alert.severity.toUpperCase()}] {alert.device_id}
                  </span>
                  <span style={{ fontSize: 10, color: "#4b5563" }}>
                    {new Date(alert.created_at).toLocaleTimeString("zh-CN", { hour12: false })}
                  </span>
                </div>
                <div style={{ fontSize: 12, color: "#9ca3af", marginBottom: 6 }}>{alert.title}</div>
                <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 8 }}>{alert.description}</div>
                <div style={{ display: "flex", gap: 8 }}>
                  {alert.status === "triggered" && (
                    <button onClick={() => handleAck(alert.id)} style={btnStyle}>确认</button>
                  )}
                  {alert.status !== "resolved" && alert.status !== "false_alarm" && (
                    <button onClick={() => handleResolve(alert.id)} style={{ ...btnStyle, color: "#10b981", borderColor: "#10b981" }}>解决</button>
                  )}
                  <span style={{ fontSize: 10, padding: "2px 8px", borderRadius: 4, background: "#1f2937", color: "#6b7280" }}>
                    {alert.status}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* AI 诊断面板 */}
        <div style={{ background: "#111827", borderRadius: 12, padding: 20, border: "1px solid #1f2937" }}>
          <h3 style={{ fontSize: 14, color: "#9ca3af", marginBottom: 16 }}>AI 根因分析诊断</h3>
          <div style={{ maxHeight: 500, overflowY: "auto" }}>
            {/* 实时诊断 */}
            {diagrams(diagnoses)}
            {/* 历史诊断 */}
            {historyDiagnoses && historyDiagnoses.length > 0 && (
              <div style={{ marginTop: 16 }}>
                <div style={{ fontSize: 11, color: "#4b5563", marginBottom: 8 }}>历史诊断</div>
                {historyDiagnoses.map((d: any, i: number) => (
                  <DiagnosisCard key={i} diag={d} />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function diagrams(diagnoses: DiagnosisData[]) {
  if (diagnoses.length === 0) {
    return <div style={{ color: "#4b5563", textAlign: "center", padding: 20 }}>等待 AI 诊断结果...</div>;
  }
  return [...diagnoses].reverse().map((d, i) => <DiagnosisCard key={i} diag={d} />);
}

function DiagnosisCard({ diag }: { diag: any }) {
  const urgencyColor = diag.urgency === "critical" ? "#ef4444" : diag.urgency === "warning" ? "#f59e0b" : "#3b82f6";
  return (
    <div style={{
      padding: 14, marginBottom: 10, borderRadius: 8, background: "#0a0e1a",
      border: `1px solid ${urgencyColor}30`,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: "#e0e6ed" }}>{diag.device_id}</span>
          <span style={{
            fontSize: 10, padding: "2px 8px", borderRadius: 4,
            background: `${urgencyColor}20`, color: urgencyColor,
          }}>{diag.urgency?.toUpperCase()}</span>
          {diag.llm_used && (
            <span style={{ fontSize: 10, padding: "2px 6px", borderRadius: 4, background: "rgba(139,92,246,0.2)", color: "#8b5cf6" }}>
              LLM
            </span>
          )}
        </div>
        <span style={{ fontSize: 10, color: "#4b5563" }}>
          {diag.timestamp ? new Date(diag.timestamp).toLocaleTimeString("zh-CN", { hour12: false }) : ""}
        </span>
      </div>
      <div style={{ fontSize: 12, color: "#9ca3af", marginBottom: 6, lineHeight: 1.6 }}>
        <strong style={{ color: "#e0e6ed" }}>诊断：</strong>{diag.diagnosis}
      </div>
      <div style={{ fontSize: 12, color: "#9ca3af", lineHeight: 1.6 }}>
        <strong style={{ color: "#e0e6ed" }}>建议：</strong>{diag.recommendation}
      </div>
      {diag.rag_sources && diag.rag_sources.length > 0 && (
        <div style={{ marginTop: 6, fontSize: 10, color: "#4b5563" }}>
          参考文档: {diag.rag_sources.map((s: any, i: number) => `[${i + 1}] ${s.title}`).join("  ")}
        </div>
      )}
    </div>
  );
}

const btnStyle: React.CSSProperties = {
  padding: "3px 10px", borderRadius: 6, fontSize: 11, cursor: "pointer",
  background: "#1f2937", border: "1px solid #374151", color: "#9ca3af",
};
