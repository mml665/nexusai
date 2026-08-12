import { useState } from "react";
import Overview from "./pages/Overview";
import Devices from "./pages/Devices";
import Alerts from "./pages/Alerts";
import Maintenance from "./pages/Maintenance";
import Control from "./pages/Control";

type Page = "overview" | "devices" | "alerts" | "maintenance" | "control";

const NAV_ITEMS: { key: Page; label: string; icon: string }[] = [
  { key: "overview", label: "运营总览", icon: "📊" },
  { key: "devices", label: "设备监控", icon: "🏭" },
  { key: "alerts", label: "告警 & 诊断", icon: "🚨" },
  { key: "maintenance", label: "预测维护", icon: "🔧" },
  { key: "control", label: "故障注入", icon: "⚡" },
];

export default function App() {
  const [page, setPage] = useState<Page>("overview");

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: "#0a0e1a" }}>
      {/* 侧边栏 */}
      <nav style={{
        width: 220,
        background: "#111827",
        borderRight: "1px solid #1f2937",
        padding: "20px 0",
        flexShrink: 0,
      }}>
        <div style={{
          padding: "0 24px 24px",
          borderBottom: "1px solid #1f2937",
          marginBottom: 16,
        }}>
          <h1 style={{
            fontSize: 22,
            fontWeight: 700,
            background: "linear-gradient(135deg, #3b82f6, #8b5cf6)",
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            marginBottom: 4,
          }}>
            NexusAI
          </h1>
          <p style={{ fontSize: 12, color: "#6b7280" }}>智能工厂实时运营平台</p>
        </div>

        {NAV_ITEMS.map(item => (
          <button
            key={item.key}
            onClick={() => setPage(item.key)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              width: "100%",
              padding: "12px 24px",
              background: page === item.key ? "rgba(59,130,246,0.1)" : "transparent",
              border: "none",
              borderLeft: page === item.key ? "3px solid #3b82f6" : "3px solid transparent",
              color: page === item.key ? "#3b82f6" : "#9ca3af",
              fontSize: 14,
              fontWeight: page === item.key ? 600 : 400,
              cursor: "pointer",
              transition: "all 0.2s",
            }}
          >
            <span style={{ fontSize: 18 }}>{item.icon}</span>
            {item.label}
          </button>
        ))}

        <div style={{ position: "absolute", bottom: 20, padding: "0 24px" }}>
          <div style={{ fontSize: 11, color: "#4b5563" }}>
            <div>8 微服务 · 5 数据存储</div>
            <div>3 AI Agent · 实时流处理</div>
          </div>
        </div>
      </nav>

      {/* 主内容区 */}
      <main style={{ flex: 1, overflow: "auto", padding: 24 }}>
        {page === "overview" && <Overview />}
        {page === "devices" && <Devices />}
        {page === "alerts" && <Alerts />}
        {page === "maintenance" && <Maintenance />}
        {page === "control" && <Control />}
      </main>
    </div>
  );
}
