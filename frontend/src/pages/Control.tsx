import { useState } from "react";
import { api, usePolling } from "../api";
import { DEVICE_LIST, FAULT_TYPE_LABELS, t } from "../types";

const FAULT_TYPES = [
  { name: "bearing_wear", label: "轴承磨损", desc: "振动逐渐增大，模拟主轴轴承劣化", icon: "⚙️", color: "#f59e0b" },
  { name: "overheating", label: "过热", desc: "温度突然飙升，模拟冷却系统故障", icon: "🌡️", color: "#ef4444" },
  { name: "calibration_drift", label: "校准漂移", desc: "转速偏离设定值，模拟编码器漂移", icon: "📐", color: "#3b82f6" },
  { name: "hydraulic_leak", label: "液压泄漏", desc: "压力骤降，模拟管路泄漏", icon: "💧", color: "#8b5cf6" },
  { name: "electrical_fault", label: "电气故障", desc: "电流异常飙升，模拟电机故障", icon: "⚡", color: "#f97316" },
];

export default function Control() {
  const [selectedDevice, setSelectedDevice] = useState("CNC-A01");
  const [injecting, setInjecting] = useState(false);
  const [message, setMessage] = useState("");
  const { data: activeFaults } = usePolling(() => api.getActiveFaults(), 5000);
  const { data: simStatus } = usePolling(() => api.getSimulatorStatus(), 5000);

  const handleInject = async (faultType: string) => {
    setInjecting(true);
    setMessage("");
    try {
      await api.injectFault(selectedDevice, faultType);
      setMessage(`✅ 已注入故障: ${t(FAULT_TYPE_LABELS, faultType)} → ${selectedDevice}`);
    } catch (e: any) {
      setMessage(`❌ 注入失败: ${e.message}`);
    }
    setInjecting(false);
    setTimeout(() => setMessage(""), 5000);
  };

  const handleClear = async (deviceId: string) => {
    try {
      await api.clearFault(deviceId);
      setMessage(`✅ 已清除 ${deviceId} 的故障`);
    } catch (e: any) {
      setMessage(`❌ 清除失败: ${e.message}`);
    }
    setTimeout(() => setMessage(""), 5000);
  };

  const handleClearAll = async () => {
    try {
      await api.clearAllFaults();
      setMessage("✅ 已清除所有故障");
    } catch (e: any) {
      setMessage(`❌ 清除失败: ${e.message}`);
    }
    setTimeout(() => setMessage(""), 5000);
  };

  const activeFaultList = activeFaults?.faults || activeFaults || [];

  return (
    <div>
      <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 20, color: "#e0e6ed" }}>故障注入控制台</h2>

      {/* 模拟器状态 */}
      {simStatus && (
        <div style={{
          background: "#111827", borderRadius: 12, padding: 16, marginBottom: 20,
          border: "1px solid #1f2937", display: "flex", justifyContent: "space-between",
        }}>
          <div>
            <span style={{ fontSize: 13, color: "#9ca3af" }}>模拟器状态：</span>
            <span style={{ fontSize: 13, fontWeight: 600, color: "#10b981" }}>
              {simStatus.running ? "运行中" : "已停止"}
            </span>
          </div>
          <div style={{ fontSize: 12, color: "#6b7280" }}>
            推送间隔: {simStatus.push_interval}s · 设备数: {simStatus.device_count || 9}
          </div>
        </div>
      )}

      {/* 消息提示 */}
      {message && (
        <div style={{
          padding: "12px 16px", marginBottom: 16, borderRadius: 8,
          background: "rgba(59,130,246,0.1)", border: "1px solid rgba(59,130,246,0.3)",
          fontSize: 13, color: "#3b82f6",
        }}>
          {message}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        {/* 故障注入面板 */}
        <div style={{ background: "#111827", borderRadius: 12, padding: 20, border: "1px solid #1f2937" }}>
          <h3 style={{ fontSize: 14, color: "#9ca3af", marginBottom: 16 }}>注入新故障</h3>

          {/* 设备选择 */}
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 8 }}>选择设备</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {DEVICE_LIST.map(d => (
                <button key={d} onClick={() => setSelectedDevice(d)}
                  style={{
                    padding: "6px 12px", borderRadius: 6, fontSize: 11, cursor: "pointer",
                    background: selectedDevice === d ? "rgba(59,130,246,0.2)" : "#1f2937",
                    border: "1px solid",
                    borderColor: selectedDevice === d ? "#3b82f6" : "#374151",
                    color: selectedDevice === d ? "#3b82f6" : "#9ca3af",
                    fontWeight: selectedDevice === d ? 600 : 400,
                  }}>{d}</button>
              ))}
            </div>
          </div>

          {/* 故障类型 */}
          <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 8 }}>选择故障类型</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {FAULT_TYPES.map(ft => (
              <button
                key={ft.name}
                onClick={() => handleInject(ft.name)}
                disabled={injecting}
                style={{
                  display: "flex", alignItems: "center", gap: 12,
                  padding: "12px 16px", borderRadius: 8, cursor: injecting ? "wait" : "pointer",
                  background: "#0a0e1a", border: `1px solid ${ft.color}30`,
                  opacity: injecting ? 0.6 : 1, transition: "all 0.2s",
                }}
              >
                <span style={{ fontSize: 24 }}>{ft.icon}</span>
                <div style={{ textAlign: "left" }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: ft.color }}>{ft.label}</div>
                  <div style={{ fontSize: 11, color: "#6b7280" }}>{ft.desc}</div>
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* 活跃故障列表 */}
        <div style={{ background: "#111827", borderRadius: 12, padding: 20, border: "1px solid #1f2937" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
            <h3 style={{ fontSize: 14, color: "#9ca3af" }}>活跃故障</h3>
            {activeFaultList.length > 0 && (
              <button onClick={handleClearAll}
                style={{
                  padding: "4px 12px", borderRadius: 6, fontSize: 11, cursor: "pointer",
                  background: "rgba(239,68,68,0.1)", border: "1px solid #ef4444",
                  color: "#ef4444",
                }}>清除全部</button>
            )}
          </div>

          {activeFaultList.length === 0 ? (
            <div style={{
              textAlign: "center", padding: 60, color: "#4b5563",
            }}>
              <div style={{ fontSize: 32, marginBottom: 8 }}>✅</div>
              <div style={{ fontSize: 13 }}>所有设备运行正常</div>
            </div>
          ) : (
            <div>
              {Array.isArray(activeFaultList) ? activeFaultList.map((f: any, i: number) => (
                <div key={i} style={{
                  display: "flex", justifyContent: "space-between", alignItems: "center",
                  padding: 12, marginBottom: 8, borderRadius: 8,
                  background: "#0a0e1a", borderLeft: "3px solid #ef4444",
                }}>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "#ef4444" }}>
                      {f.device_id} — {t(FAULT_TYPE_LABELS, f.fault_type)}
                    </div>
                    <div style={{ fontSize: 11, color: "#6b7280" }}>
                      注入时间: {f.injected_at ? new Date(f.injected_at).toLocaleTimeString("zh-CN", { hour12: false }) : "—"}
                    </div>
                  </div>
                  <button onClick={() => handleClear(f.device_id)}
                    style={{
                      padding: "4px 10px", borderRadius: 6, fontSize: 11, cursor: "pointer",
                      background: "#1f2937", border: "1px solid #374151", color: "#9ca3af",
                    }}>清除</button>
                </div>
              )) : Object.entries(activeFaultList).map(([deviceId, fault]: [string, any]) => (
                <div key={deviceId} style={{
                  display: "flex", justifyContent: "space-between", alignItems: "center",
                  padding: 12, marginBottom: 8, borderRadius: 8,
                  background: "#0a0e1a", borderLeft: "3px solid #ef4444",
                }}>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "#ef4444" }}>
                      {deviceId} — {typeof fault === "string" ? t(FAULT_TYPE_LABELS, fault) : t(FAULT_TYPE_LABELS, fault?.fault_type || "") || "未知"}
                    </div>
                  </div>
                  <button onClick={() => handleClear(deviceId)}
                    style={{
                      padding: "4px 10px", borderRadius: 6, fontSize: 11, cursor: "pointer",
                      background: "#1f2937", border: "1px solid #374151", color: "#9ca3af",
                    }}>清除</button>
                </div>
              ))}
            </div>
          )}

          {/* 演示提示 */}
          <div style={{
            marginTop: 20, padding: 14, borderRadius: 8,
            background: "rgba(139,92,246,0.05)", border: "1px solid rgba(139,92,246,0.2)",
          }}>
            <div style={{ fontSize: 12, color: "#8b5cf6", fontWeight: 600, marginBottom: 6 }}>💡 演示流程</div>
            <div style={{ fontSize: 11, color: "#9ca3af", lineHeight: 1.8 }}>
              1. 选择设备并注入故障<br/>
              2. 切换到「运营总览」看实时异常检测<br/>
              3. 切换到「告警 & 诊断」看 AI 根因分析<br/>
              4. 切换到「预测维护」看健康度变化<br/>
              5. 回到这里清除故障，观察恢复过程
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
