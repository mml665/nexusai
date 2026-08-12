import { api, usePolling, useRealtimeSensors, useWebSocket, useWebSocketStream } from "../api";
import ReactECharts from "echarts-for-react";
import type { OverviewData, AnomalyEvent, OEEData } from "../types";
import { SEVERITY_COLORS, LINE_COLORS } from "../types";

// ── 工具函数 ──

function StatCard({ title, value, unit, color, sub }: { title: string; value: string | number; unit?: string; color?: string; sub?: string }) {
  return (
    <div style={{
      background: "#111827",
      borderRadius: 12,
      padding: 20,
      border: "1px solid #1f2937",
    }}>
      <div style={{ fontSize: 13, color: "#6b7280", marginBottom: 8 }}>{title}</div>
      <div style={{ fontSize: 32, fontWeight: 700, color: color || "#e0e6ed" }}>
        {value}<span style={{ fontSize: 14, color: "#6b7280", marginLeft: 4 }}>{unit}</span>
      </div>
      {sub && <div style={{ fontSize: 12, color: "#6b7280", marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

function OEEGauge({ value, label }: { value: number; label: string }) {
  const color = value >= 75 ? "#10b981" : value >= 50 ? "#f59e0b" : "#ef4444";
  return (
    <ReactECharts
      style={{ height: 160 }}
      option={{
        series: [{
          type: "gauge",
          startAngle: 200,
          endAngle: -20,
          min: 0,
          max: 100,
          radius: "90%",
          progress: { show: true, width: 10, roundCap: true },
          axisLine: { lineStyle: { width: 10, color: [[1, "#1f2937"]] } },
          axisTick: { show: false },
          splitLine: { show: false },
          axisLabel: { show: false },
          pointer: { show: false },
          detail: {
            valueAnimation: true,
            fontSize: 28,
            fontWeight: 700,
            color,
            offsetCenter: [0, 0],
            formatter: "{value}%",
          },
          title: { show: true, fontSize: 12, color: "#6b7280", offsetCenter: [0, 30] },
          data: [{ value: Math.round(value), name: label }],
          itemStyle: { color },
        }],
      }}
    />
  );
}

// ── 主组件 ──

export default function Overview() {
  const { data: overview } = usePolling<OverviewData>(() => api.getOverview(), 5000);
  const { data: latestOEE } = usePolling<{ data: OEEData[] }>(() => api.getLatestOEE(), 5000);
  const sensors = useRealtimeSensors();
  const anomalies = useWebSocketStream<AnomalyEvent>("anomaly", 20);
  const diagnosis = useWebSocket<any>("diagnosis");

  // OEE 趋势数据
  const oeeHistory = usePolling<{ data: OEEData[] }>(() => api.getOEE(undefined, 1), 10000);

  if (!overview) return <div style={{ color: "#6b7280" }}>加载中...</div>;

  const s = overview.summary;
  const oeeByDevice = latestOEE?.data || overview.oee_by_device;

  // OEE 趋势图 option
  const oeeTrendOption = {
    tooltip: { trigger: "axis" },
    legend: { data: oeeByDevice.map(d => d.device_id).slice(0, 5), textStyle: { color: "#9ca3af" }, top: 0 },
    grid: { top: 40, right: 20, bottom: 30, left: 50 },
    xAxis: {
      type: "category",
      data: (oeeHistory.data?.data || []).slice(-60).map(r => new Date(r.time).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })),
      axisLabel: { color: "#6b7280", fontSize: 10 },
      axisLine: { lineStyle: { color: "#1f2937" } },
    },
    yAxis: {
      type: "value",
      min: 0,
      max: 100,
      axisLabel: { color: "#6b7280" },
      splitLine: { lineStyle: { color: "#1f2937" } },
    },
    series: oeeByDevice.slice(0, 5).map(d => ({
      name: d.device_id,
      type: "line",
      smooth: true,
      symbol: "none",
      lineStyle: { width: 2 },
      data: (oeeHistory.data?.data || []).filter(r => r.device_id === d.device_id).slice(-60).map(r => r.oee),
    })),
  };

  return (
    <div>
      <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 20, color: "#e0e6ed" }}>运营总览</h2>

      {/* 顶部统计卡片 */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 20 }}>
        <StatCard title="设备综合效率 (OEE)" value={s.avg_oee.toFixed(1)} unit="%" color={s.avg_oee >= 75 ? "#10b981" : s.avg_oee >= 50 ? "#f59e0b" : "#ef4444"} sub={`运行设备 ${s.running_devices}/${s.total_devices}`} />
        <StatCard title="累计产量" value={s.total_output} unit="件" color="#3b82f6" sub={`不良品 ${s.total_defects} 件`} />
        <StatCard title="良率" value={(100 - s.defect_rate).toFixed(1)} unit="%" color={s.defect_rate < 3 ? "#10b981" : "#f59e0b"} sub={`不良率 ${s.defect_rate.toFixed(1)}%`} />
        <StatCard title="活跃告警" value={s.active_alerts} unit="条" color={s.active_alerts > 0 ? "#ef4444" : "#10b981"} sub={diagnosis ? `最新诊断: ${diagnosis.device_id}` : "无新诊断"} />
      </div>

      {/* OEE 趋势 + 仪表盘 */}
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 16, marginBottom: 20 }}>
        <div style={{ background: "#111827", borderRadius: 12, padding: 20, border: "1px solid #1f2937" }}>
          <h3 style={{ fontSize: 14, color: "#9ca3af", marginBottom: 12 }}>OEE 趋势（最近 1 小时）</h3>
          <ReactECharts style={{ height: 280 }} option={oeeTrendOption} />
        </div>
        <div style={{ background: "#111827", borderRadius: 12, padding: 20, border: "1px solid #1f2937" }}>
          <h3 style={{ fontSize: 14, color: "#9ca3af", marginBottom: 12 }}>各产线 OEE</h3>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
            {["A", "B", "C"].map(line => {
              const lineDevices = oeeByDevice.filter(d => overview.devices.find(dev => dev.device_id === d.device_id)?.line === line);
              const avgOEE = lineDevices.length > 0 ? lineDevices.reduce((sum, d) => sum + d.oee, 0) / lineDevices.length : 0;
              return <OEEGauge key={line} value={avgOEE} label={`产线 ${line}`} />;
            })}
          </div>
        </div>
      </div>

      {/* 设备状态 + 异常事件流 */}
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 16 }}>
        <div style={{ background: "#111827", borderRadius: 12, padding: 20, border: "1px solid #1f2937" }}>
          <h3 style={{ fontSize: 14, color: "#9ca3af", marginBottom: 12 }}>设备实时状态</h3>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
            {overview.devices.map(dev => {
              const sensorData = sensors[dev.device_id];
              const oee = oeeByDevice.find(d => d.device_id === dev.device_id);
              const isRunning = sensorData?.status === "running" || dev.status === "running";
              return (
                <div key={dev.device_id} style={{
                  background: "#0a0e1a",
                  borderRadius: 8,
                  padding: 12,
                  border: `1px solid ${isRunning ? "#1f2937" : "#ef4444"}40`,
                }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                    <span style={{ fontSize: 13, fontWeight: 600, color: "#e0e6ed" }}>{dev.device_id}</span>
                    <span style={{
                      width: 8, height: 8, borderRadius: "50%",
                      background: isRunning ? "#10b981" : "#ef4444",
                      boxShadow: isRunning ? "0 0 6px #10b981" : "0 0 6px #ef4444",
                    }} />
                  </div>
                  <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 6 }}>{dev.name}</div>
                  {sensorData && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                      {Object.entries(sensorData.sensors).slice(0, 4).map(([k, v]) => (
                        <span key={k} style={{
                          fontSize: 10, padding: "2px 6px", borderRadius: 4,
                          background: "#1f2937", color: "#9ca3af",
                        }}>
                          {k.split("_").map(w => w[0]).join("")}: {typeof v === "number" ? v.toFixed(1) : v}
                        </span>
                      ))}
                    </div>
                  )}
                  {oee && (
                    <div style={{ fontSize: 11, color: LINE_COLORS[dev.line], marginTop: 6 }}>
                      OEE: {oee.oee.toFixed(1)}% · 产出: {oee.output_count}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* 异常事件流 */}
        <div style={{ background: "#111827", borderRadius: 12, padding: 20, border: "1px solid #1f2937" }}>
          <h3 style={{ fontSize: 14, color: "#9ca3af", marginBottom: 12 }}>实时异常检测</h3>
          <div style={{ maxHeight: 400, overflowY: "auto" }}>
            {anomalies.length === 0 ? (
              <div style={{ color: "#4b5563", fontSize: 13, textAlign: "center", padding: 40 }}>暂无异常事件</div>
            ) : (
              [...anomalies].reverse().map((ev, i) => (
                <div key={i} style={{
                  padding: 10,
                  marginBottom: 8,
                  borderRadius: 8,
                  background: "#0a0e1a",
                  borderLeft: `3px solid ${SEVERITY_COLORS[ev.severity] || "#6b7280"}`,
                }}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                    <span style={{ fontSize: 12, fontWeight: 600, color: SEVERITY_COLORS[ev.severity] || "#9ca3af" }}>
                      {ev.severity.toUpperCase()}
                    </span>
                    <span style={{ fontSize: 10, color: "#4b5563" }}>{ev.device_id}</span>
                  </div>
                  <div style={{ fontSize: 11, color: "#9ca3af" }}>{ev.message}</div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
