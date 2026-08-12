import { useState } from "react";

const API_BASE = "/api/v1";

export default function Login({ onLogin }: { onLogin: (token: string, user: any) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const resp = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });

      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data?.error?.message || data?.detail || `登录失败 (${resp.status})`);
      }

      const data = await resp.json();
      onLogin(data.access_token, data.user);
    } catch (err: any) {
      setError(err.message || "登录失败，请重试");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      display: "flex",
      minHeight: "100vh",
      alignItems: "center",
      justifyContent: "center",
      background: "linear-gradient(135deg, #0a0e1a 0%, #111827 50%, #1a1040 100%)",
    }}>
      <div style={{
        width: 400,
        padding: 40,
        background: "rgba(17, 24, 39, 0.8)",
        backdropFilter: "blur(20px)",
        borderRadius: 16,
        border: "1px solid rgba(59, 130, 246, 0.2)",
        boxShadow: "0 20px 60px rgba(0, 0, 0, 0.5)",
      }}>
        {/* Logo */}
        <div style={{ textAlign: "center", marginBottom: 32 }}>
          <h1 style={{
            fontSize: 32,
            fontWeight: 800,
            background: "linear-gradient(135deg, #3b82f6, #8b5cf6)",
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            marginBottom: 8,
          }}>
            NexusAI
          </h1>
          <p style={{ fontSize: 13, color: "#6b7280" }}>智能工厂实时运营平台</p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 20 }}>
            <label style={{ display: "block", fontSize: 13, color: "#9ca3af", marginBottom: 8 }}>
              用户名
            </label>
            <input
              type="text"
              value={username}
              onChange={e => setUsername(e.target.value)}
              placeholder="请输入用户名"
              required
              style={{
                width: "100%",
                padding: "12px 16px",
                background: "rgba(31, 41, 55, 0.5)",
                border: "1px solid #374151",
                borderRadius: 8,
                color: "#f3f4f6",
                fontSize: 14,
                outline: "none",
                boxSizing: "border-box",
                transition: "border-color 0.2s",
              }}
              onFocus={e => e.target.style.borderColor = "#3b82f6"}
              onBlur={e => e.target.style.borderColor = "#374151"}
            />
          </div>

          <div style={{ marginBottom: 24 }}>
            <label style={{ display: "block", fontSize: 13, color: "#9ca3af", marginBottom: 8 }}>
              密码
            </label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="请输入密码"
              required
              style={{
                width: "100%",
                padding: "12px 16px",
                background: "rgba(31, 41, 55, 0.5)",
                border: "1px solid #374151",
                borderRadius: 8,
                color: "#f3f4f6",
                fontSize: 14,
                outline: "none",
                boxSizing: "border-box",
                transition: "border-color 0.2s",
              }}
              onFocus={e => e.target.style.borderColor = "#3b82f6"}
              onBlur={e => e.target.style.borderColor = "#374151"}
            />
          </div>

          {error && (
            <div style={{
              padding: "10px 14px",
              background: "rgba(239, 68, 68, 0.1)",
              border: "1px solid rgba(239, 68, 68, 0.3)",
              borderRadius: 8,
              color: "#ef4444",
              fontSize: 13,
              marginBottom: 16,
            }}>
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            style={{
              width: "100%",
              padding: "12px",
              background: loading
                ? "rgba(59, 130, 246, 0.5)"
                : "linear-gradient(135deg, #3b82f6, #6366f1)",
              border: "none",
              borderRadius: 8,
              color: "white",
              fontSize: 15,
              fontWeight: 600,
              cursor: loading ? "not-allowed" : "pointer",
              transition: "all 0.2s",
            }}
          >
            {loading ? "登录中..." : "登 录"}
          </button>
        </form>

        {/* Demo credentials */}
        <div style={{
          marginTop: 24,
          padding: "12px 16px",
          background: "rgba(59, 130, 246, 0.05)",
          border: "1px solid rgba(59, 130, 246, 0.1)",
          borderRadius: 8,
        }}>
          <p style={{ fontSize: 12, color: "#6b7280", marginBottom: 6 }}>演示账号</p>
          <div style={{ fontSize: 12, color: "#9ca3af", lineHeight: 1.8 }}>
            <div>管理员: <span style={{ color: "#3b82f6" }}>admin</span> / admin123</div>
            <div>操作员: <span style={{ color: "#3b82f6" }}>operator</span> / operator123</div>
            <div>观察者: <span style={{ color: "#3b82f6" }}>viewer</span> / viewer123</div>
          </div>
        </div>
      </div>
    </div>
  );
}
