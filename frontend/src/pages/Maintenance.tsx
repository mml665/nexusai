import { useState } from "react";
import { api, usePolling } from "../api";
import ReactECharts from "echarts-for-react";
import { RISK_COLORS, RISK_LABELS, TREND_LABELS, SENSOR_LABELS, DEVICE_LIST, t } from "../types";

export default function Maintenance() {
  const { data: maintenanceData, loading } = usePolling(() => api.triggerMaintenanceAll(), 60000);
  const { data: diagnoses } = usePolling(() => api.getDiagnoses(5), 10000);
  const [selectedDevice, setSelectedDevice] = useState<string>("");
  const { data: history } = usePolling(
    () => selectedDevice ? api.getMaintenanceHistory(selectedDevice) : Promise.resolve([]),
    15000,
    [selectedDevice]
  );

  const results = maintenanceData?.results || [];

  // 健康度雷达图
  const radarOption = {
    tooltip: {},
    radar: {
      indicator: results.slice(0, 9).map(r => ({ name: r.device_id, max: 100 })),
      axisName: { color: "#9ca3af", fontSize: 10 },
      splitLine: { lineStyle: { color: "#1f2937" } },
      splitArea: { areaStyle: { color: ["#0a0e1a", "#111827"] } },
      axisLine: { lineStyle: { color: "#1f2937" } },
    },
    series: [{
      type: "radar",
      data: [{
        value: results.map(r => r.health_score || 0),
        name: "健康度",
        areaStyle: { color: "rgba(59,130,246,0.2)" },
        lineStyle: { color: "#3b82f6", width: 2 },
        itemStyle: { color: "#3b82f6" },
      }],
    }],
  };

  return (
    <div>
      <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 20, color: "#e0e6ed" }}>预测性维护</h2>

      {loading && results.length === 0 ? (
        <div style={{ color: "#6b7280" }}>正在分析设备健康度...</div>
      ) : (
        <>
          {/* 设备健康度卡片 */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginBottom: 20 }}>
            {results.map(r => (
              <div
                key={r.device_id}
                onClick={() => setSelectedDevice(r.device_id)}
                style={{
                  background: "#111827", borderRadius: 12, padding: 16,
                  border: `1px solid ${selectedDevice === r.device_id ? "#3b82f6" : "#1f2937"}`,
                  cursor: "pointer", transition: "all 0.2s",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: "#e0e6ed" }}>{r.device_id}</span>
                  <span style={{
                    fontSize: 10, padding: "2px 8px", borderRadius: 4,
                    background: `${RISK_COLORS[r.risk_level]}20`,
                    color: RISK_COLORS[r.risk_level],
                  }}>{t(RISK_LABELS, r.risk_level)}</span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  {/* 健康度环形进度 */}
                  <div style={{
                    width: 60, height: 60, borderRadius: "50%",
                    background: `conic-gradient(${RISK_COLORS[r.risk_level]} ${r.health_score * 3.6}deg, #1f2937 0deg)`,
                    display: "flex", alignItems: "center", justifyContent: "center",
                  }}>
                    <div style={{
                      width: 48, height: 48, borderRadius: "50%", background: "#111827",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      fontSize: 18, fontWeight: 700, color: RISK_COLORS[r.risk_level],
                    }}>
                      {r.health_score}
                    </div>
                  </div>
                  <div>
                    {r.predicted_rul !== null && r.predicted_rul !== undefined ? (
                      <>
                        <div style={{ fontSize: 11, color: "#6b7280" }}>剩余寿命</div>
                        <div style={{ fontSize: 16, fontWeight: 600, color: "#e0e6ed" }}>{r.predicted_rul}h</div>
                      </>
                    ) : (
                      <div style={{ fontSize: 11, color: "#6b7280" }}>寿命预测中</div>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* 雷达图 + 趋势详情 */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <div style={{ background: "#111827", borderRadius: 12, padding: 20, border: "1px solid #1f2937" }}>
              <h3 style={{ fontSize: 14, color: "#9ca3af", marginBottom: 12 }}>设备健康度全景</h3>
              <ReactECharts style={{ height: 300 }} option={radarOption} />
            </div>

            <div style={{ background: "#111827", borderRadius: 12, padding: 20, border: "1px solid #1f2937" }}>
              <h3 style={{ fontSize: 14, color: "#9ca3af", marginBottom: 12 }}>
                {selectedDevice ? `${selectedDevice} 维保详情` : "点击左侧设备查看详情"}
              </h3>
              {selectedDevice && (() => {
                const detail = results.find(r => r.device_id === selectedDevice);
                if (!detail) return null;
                return (
                  <div>
                    <div style={{ marginBottom: 12, padding: 12, background: "#0a0e1a", borderRadius: 8 }}>
                      <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 4 }}>维护建议</div>
                      <div style={{ fontSize: 13, color: "#9ca3af", lineHeight: 1.6 }}>{detail.recommendation}</div>
                    </div>
                    {detail.trends && Object.entries(detail.trends).map(([sensor, td]: [string, any]) => (
                      <div key={sensor} style={{
                        display: "flex", justifyContent: "space-between",
                        padding: "8px 12px", marginBottom: 4, borderRadius: 6,
                        background: "#0a0e1a",
                      }}>
                        <span style={{ fontSize: 12, color: "#9ca3af" }}>{t(SENSOR_LABELS, sensor)}</span>
                        <div style={{ display: "flex", gap: 12, fontSize: 11 }}>
                          <span style={{ color: "#6b7280" }}>当前: {td.current}</span>
                          <span style={{ color: td.trend === "rising" ? "#ef4444" : td.trend === "falling" ? "#3b82f6" : "#6b7280" }}>
                            {t(TREND_LABELS, td.trend)}
                          </span>
                          {td.rul_hours !== null && (
                            <span style={{ color: RISK_COLORS[detail.risk_level] }}>剩余寿命: {td.rul_hours}小时</span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                );
              })()}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
