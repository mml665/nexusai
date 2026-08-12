import { useState, useEffect } from "react";
import { api, useRealtimeSensors, usePolling } from "../api";
import ReactECharts from "echarts-for-react";
import { LINE_COLORS, SENSOR_LABELS, t } from "../types";

export default function Devices() {
  const sensors = useRealtimeSensors();
  const { data: devicesData } = usePolling(() => api.getDevices(), 10000);
  const [selectedDevice, setSelectedDevice] = useState<string>("CNC-A01");
  const [sensorHistory, setSensorHistory] = useState<Record<string, { time: string; value: number }[]>>({});

  // 实时收集传感器历史
  useEffect(() => {
    if (!sensors[selectedDevice]) return;
    const reading = sensors[selectedDevice];
    const time = new Date(reading.timestamp).toLocaleTimeString("zh-CN", { hour12: false });
    setSensorHistory(prev => {
      const next = { ...prev };
      for (const [sensorType, value] of Object.entries(reading.sensors)) {
        if (!next[sensorType]) next[sensorType] = [];
        next[sensorType] = [...next[sensorType].slice(-59), { time, value: value as number }];
      }
      return next;
    });
  }, [sensors, selectedDevice]);

  const devices = devicesData?.data || [];
  const selectedReading = sensors[selectedDevice];

  // 传感器图表 option
  const sensorChartOption = (sensorType: string, data: { time: string; value: number }[]) => ({
    tooltip: { trigger: "axis" },
    grid: { top: 30, right: 15, bottom: 25, left: 50 },
    xAxis: {
      type: "category",
      data: data.map(d => d.time),
      axisLabel: { color: "#6b7280", fontSize: 9 },
      axisLine: { lineStyle: { color: "#1f2937" } },
    },
    yAxis: {
      type: "value",
      axisLabel: { color: "#6b7280", fontSize: 10 },
      splitLine: { lineStyle: { color: "#1f2937" } },
    },
    series: [{
      type: "line",
      smooth: true,
      symbol: "none",
      data: data.map(d => d.value),
      lineStyle: { width: 2, color: "#3b82f6" },
      areaStyle: {
        color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [
          { offset: 0, color: "rgba(59,130,246,0.3)" },
          { offset: 1, color: "rgba(59,130,246,0)" },
        ]},
      },
    }],
    title: { text: t(SENSOR_LABELS, sensorType), left: 10, top: 5, textStyle: { color: "#9ca3af", fontSize: 12 } },
  });

  return (
    <div>
      <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 20, color: "#e0e6ed" }}>设备监控</h2>

      {/* 设备选择网格 */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginBottom: 20 }}>
        {["A", "B", "C"].map(line => (
          <div key={line}>
            <div style={{
              fontSize: 13, color: LINE_COLORS[line], marginBottom: 8, fontWeight: 600,
            }}>产线 {line}</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {devices.filter(d => d.line === line).map(dev => {
                const reading = sensors[dev.device_id];
                const isSelected = selectedDevice === dev.device_id;
                const isRunning = reading?.status === "running" || dev.status === "running";
                return (
                  <button
                    key={dev.device_id}
                    onClick={() => setSelectedDevice(dev.device_id)}
                    style={{
                      display: "flex", justifyContent: "space-between", alignItems: "center",
                      padding: "10px 14px", borderRadius: 8, cursor: "pointer",
                      background: isSelected ? "rgba(59,130,246,0.1)" : "#111827",
                      border: isSelected ? "1px solid #3b82f6" : "1px solid #1f2937",
                      transition: "all 0.2s",
                    }}
                  >
                    <div style={{ textAlign: "left" }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: isSelected ? "#3b82f6" : "#e0e6ed" }}>{dev.device_id}</div>
                      <div style={{ fontSize: 10, color: "#6b7280" }}>{dev.name}</div>
                    </div>
                    <span style={{
                      width: 8, height: 8, borderRadius: "50%",
                      background: isRunning ? "#10b981" : "#ef4444",
                      boxShadow: isRunning ? "0 0 6px #10b981" : "0 0 6px #ef4444",
                    }} />
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* 选中设备的实时传感器图表 */}
      <div style={{ background: "#111827", borderRadius: 12, padding: 20, border: "1px solid #1f2937" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <h3 style={{ fontSize: 14, color: "#9ca3af" }}>
            {selectedDevice} 实时传感器数据
          </h3>
          {selectedReading && (
            <span style={{ fontSize: 11, color: "#4b5563" }}>
              最后更新: {new Date(selectedReading.timestamp).toLocaleTimeString("zh-CN", { hour12: false })}
            </span>
          )}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          {Object.keys(sensorHistory).map(sensorType => (
            <div key={sensorType} style={{
              background: "#0a0e1a", borderRadius: 8, padding: 12, border: "1px solid #1f2937",
            }}>
              <ReactECharts
                style={{ height: 180 }}
                option={sensorChartOption(sensorType, sensorHistory[sensorType])}
              />
              {selectedReading && (
                <div style={{ fontSize: 16, fontWeight: 700, color: "#3b82f6", textAlign: "center" }}>
                  {selectedReading.sensors[sensorType]?.toFixed(2)}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
