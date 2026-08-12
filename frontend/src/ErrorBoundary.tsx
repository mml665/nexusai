import { Component, ReactNode } from "react";

interface Props {
  children: ReactNode;
  pageName?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error(`[ErrorBoundary${this.props.pageName ? ":" + this.props.pageName : ""}]`, error, info);
  }

  handleReload = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 40, textAlign: "center" }}>
          <div style={{ fontSize: 48, marginBottom: 16 }}>⚠️</div>
          <h2 style={{ fontSize: 18, color: "#ef4444", marginBottom: 8 }}>页面渲染出错</h2>
          <p style={{ fontSize: 13, color: "#9ca3af", marginBottom: 4 }}>
            {this.props.pageName ? `${this.props.pageName} ` : ""}页面遇到了一个错误
          </p>
          <p style={{ fontSize: 12, color: "#6b7280", marginBottom: 16, fontFamily: "monospace" }}>
            {this.state.error?.message || "未知错误"}
          </p>
          <button
            onClick={this.handleReload}
            style={{
              padding: "8px 20px", borderRadius: 8, fontSize: 13, cursor: "pointer",
              background: "#3b82f6", color: "#fff", border: "none", fontWeight: 500,
            }}
          >
            重试
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
