import { useState, useEffect } from "react";
import Overview from "./pages/Overview";
import Devices from "./pages/Devices";
import Alerts from "./pages/Alerts";
import Maintenance from "./pages/Maintenance";
import Control from "./pages/Control";
import Login from "./pages/Login";
import ErrorBoundary from "./ErrorBoundary";
import { getToken, clearToken, getUser, setUser } from "./api";

type Page = "overview" | "devices" | "alerts" | "maintenance" | "control";

const NAV_ITEMS: { key: Page; label: string; icon: string; roles?: string[] }[] = [
  { key: "overview", label: "运营总览", icon: "📊" },
  { key: "devices", label: "设备监控", icon: "🏭" },
  { key: "alerts", label: "告警 & 诊断", icon: "🚨" },
  { key: "maintenance", label: "预测维护", icon: "🔧" },
  { key: "control", label: "故障注入", icon: "⚡", roles: ["admin", "operator"] },
];

export default function App() {
  const [page, setPage] = useState<Page>("overview");
  const [authed, setAuthed] = useState<boolean>(false);
  const [user, setUserState] = useState<any>(null);
  const [validating, setValidating] = useState<boolean>(true);

  // Validate token on mount: presence alone is not enough, ask gateway.
  useEffect(() => {
    const validate = async () => {
      const token = getToken();
      if (!token) {
        setAuthed(false);
        setValidating(false);
        return;
      }
      try {
        const resp = await fetch("/api/v1/auth/me", {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!resp.ok) throw new Error("invalid token");
        const userData = await resp.json();
        setUser(userData);
        setUserState(userData);
        setAuthed(true);
      } catch {
        clearToken();
        setAuthed(false);
      } finally {
        setValidating(false);
      }
    };
    validate();
  }, []);

  const handleLogin = (token: string, userData: any) => {
    localStorage.setItem("nexusai_token", token);
    localStorage.setItem("nexusai_user", JSON.stringify(userData));
    setAuthed(true);
    setUserState(userData);
  };

  const handleLogout = () => {
    clearToken();
    setAuthed(false);
    setUserState(null);
  };

  // Show spinner while validating token to avoid 401 reload loops.
  if (validating) {
    return (
      <div style={{
        minHeight: "100vh",
        background: "#0a0e1a",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "#9ca3af",
        fontSize: 14,
      }}>
        验证登录状态中...
      </div>
    );
  }

  // Show login page if not authenticated
  if (!authed) {
    return <Login onLogin={handleLogin} />;
  }

  const userRole = user?.role || "viewer";
  const visibleNavItems = NAV_ITEMS.filter(item => !item.roles || item.roles.includes(userRole));

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: "#0a0e1a" }}>
      {/* 侧边栏 */}
      <nav style={{
        width: 220,
        background: "#111827",
        borderRight: "1px solid #1f2937",
        padding: "20px 0",
        flexShrink: 0,
        display: "flex",
        flexDirection: "column",
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

        {visibleNavItems.map(item => (
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

        {/* User info + Logout */}
        <div style={{ marginTop: "auto", borderTop: "1px solid #1f2937", paddingTop: 16, padding: "16px 24px" }}>
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 13, color: "#e5e7eb", fontWeight: 500 }}>
              {user?.username || "unknown"}
            </div>
            <div style={{ fontSize: 11, color: "#6b7280" }}>
              角色: {user?.role || "viewer"}
            </div>
          </div>
          <button
            onClick={handleLogout}
            style={{
              width: "100%",
              padding: "8px 12px",
              background: "rgba(239, 68, 68, 0.1)",
              border: "1px solid rgba(239, 68, 68, 0.2)",
              borderRadius: 6,
              color: "#ef4444",
              fontSize: 13,
              fontWeight: 500,
              cursor: "pointer",
              transition: "all 0.2s",
            }}
          >
            退出登录
          </button>
          <div style={{ fontSize: 11, color: "#4b5563", marginTop: 12 }}>
            <div>8 微服务 · 5 数据存储</div>
            <div>3 AI Agent · Prometheus 监控</div>
          </div>
        </div>
      </nav>

      {/* 主内容区 */}
      <main style={{ flex: 1, overflow: "auto", padding: 24 }}>
        <ErrorBoundary pageName="运营总览">
          {page === "overview" && <Overview />}
        </ErrorBoundary>
        <ErrorBoundary pageName="设备监控">
          {page === "devices" && <Devices />}
        </ErrorBoundary>
        <ErrorBoundary pageName="告警&诊断">
          {page === "alerts" && <Alerts />}
        </ErrorBoundary>
        <ErrorBoundary pageName="预测维护">
          {page === "maintenance" && <Maintenance />}
        </ErrorBoundary>
        <ErrorBoundary pageName="故障注入">
          {page === "control" && <Control />}
        </ErrorBoundary>
      </main>
    </div>
  );
}
