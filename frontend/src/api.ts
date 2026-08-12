// ── API 客户端 + WebSocket Hooks ──

import { useEffect, useRef, useState, useCallback } from "react";
import type {
  OverviewData,
  OEEData,
  AlertData,
  DiagnosisData,
  MaintenanceData,
  SensorReading,
  AnomalyEvent,
} from "./types";

const API_BASE = "/api/v1";

// ── REST API ──

async function apiGet<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`);
  if (!resp.ok) throw new Error(`API ${path}: ${resp.status}`);
  return resp.json();
}

async function apiPost<T>(path: string, body?: any): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) throw new Error(`API ${path}: ${resp.status}`);
  return resp.json();
}

async function apiPut<T>(path: string, body?: any): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) throw new Error(`API ${path}: ${resp.status}`);
  return resp.json();
}

export const api = {
  getOverview: () => apiGet<OverviewData>("/metrics/overview"),
  getOEE: (deviceId?: string, hours = 1) =>
    apiGet<{ data: OEEData[] }>(`/metrics/oee?${deviceId ? `device_id=${deviceId}&` : ""}hours=${hours}`),
  getLatestOEE: () => apiGet<{ data: OEEData[] }>("/metrics/oee/latest"),
  getSensorReadings: (deviceId: string, sensorType?: string, minutes = 10) =>
    apiGet<{ data: any[] }>(`/metrics/sensors?device_id=${deviceId}${sensorType ? `&sensor_type=${sensorType}` : ""}&minutes=${minutes}`),
  getOutputStats: (hours = 1) =>
    apiGet<{ data: any[] }>(`/metrics/output?hours=${hours}`),

  getAlerts: (params?: { status?: string; severity?: string; device_id?: string }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set("status", params.status);
    if (params?.severity) qs.set("severity", params.severity);
    if (params?.device_id) qs.set("device_id", params.device_id);
    return apiGet<{ data: AlertData[] }>(`/alerts?${qs}`);
  },
  getAlertStats: () => apiGet<any>("/alerts/stats"),
  acknowledgeAlert: (id: number) => apiPut(`/alerts/${id}/acknowledge`),
  resolveAlert: (id: number) => apiPut(`/alerts/${id}/resolve`),

  getDevices: () => apiGet<{ data: any[] }>("/devices"),
  triggerMaintenance: (deviceId: string) => apiPost(`/ai/maintenance/${deviceId}`),
  triggerMaintenanceAll: () => apiPost("/ai/maintenance"),
  triggerDiagnosis: (deviceId: string, body?: any) => apiPost(`/ai/diagnosis/${deviceId}`, body),
  getDiagnoses: (limit = 20) => apiGet<any[]>(`/ai/diagnoses?limit=${limit}`),
  getMaintenanceHistory: (deviceId: string) => apiGet<any[]>(`/ai/maintenance/history/${deviceId}`),

  injectFault: (deviceId: string, faultType: string) =>
    apiPost(`/faults/inject`, { device_id: deviceId, fault_type: faultType }),
  clearFault: (deviceId: string) =>
    fetch(`${API_BASE}/faults/${deviceId}`, { method: "DELETE" }).then(r => r.json()),
  clearAllFaults: () =>
    fetch(`${API_BASE}/faults/active`, { method: "DELETE" }).then(r => r.json()),
  getSimulatorStatus: () => apiGet<any>("/simulator/status"),
  getActiveFaults: () => apiGet<any>("/faults/active"),
  getFaultTypes: () => apiGet<any>("/faults/types"),

  getWorkOrders: () => apiGet<{ data: any[] }>("/workorders"),
  createWorkOrder: (body: any) => apiPost("/workorders", body),
};

// ── WebSocket Hook ──

export function useWebSocket<T = any>(channel: string): T | null {
  const [data, setData] = useState<T | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<number>();

  const connect = useCallback(() => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/${channel}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        setData(msg);
      } catch {
        // 非 JSON 消息，直接存
        setData(ev.data as any);
      }
    };

    ws.onclose = () => {
      reconnectTimer.current = window.setTimeout(connect, 3000);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [channel]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [connect]);

  return data;
}

// ── WebSocket 多消息 Hook（保留历史） ──

export function useWebSocketStream<T = any>(channel: string, maxItems = 50): T[] {
  const [items, setItems] = useState<T[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<number>();

  const connect = useCallback(() => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/${channel}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        setItems(prev => [...prev.slice(-(maxItems - 1)), msg]);
      } catch {
        // ignore
      }
    };

    ws.onclose = () => {
      reconnectTimer.current = window.setTimeout(connect, 3000);
    };

    ws.onerror = () => ws.close();
  }, [channel, maxItems]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [connect]);

  return items;
}

// ── 实时传感器数据 Hook ──

export function useRealtimeSensors(): Record<string, SensorReading> {
  const latest = useWebSocketStream<SensorReading>("sensors", 200);
  const [byDevice, setByDevice] = useState<Record<string, SensorReading>>({});

  useEffect(() => {
    if (latest.length === 0) return;
    const last = latest[latest.length - 1];
    if (last?.device_id) {
      setByDevice(prev => ({ ...prev, [last.device_id]: last }));
    }
  }, [latest]);

  return byDevice;
}

// ── 定时刷新 Hook ──

export function usePolling<T>(fetcher: () => Promise<T>, intervalMs: number, deps: any[] = []): { data: T | null; loading: boolean; error: string | null } {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const result = await fetcher();
        if (!cancelled) {
          setData(result);
          setError(null);
          setLoading(false);
        }
      } catch (e: any) {
        if (!cancelled) {
          setError(e.message);
          setLoading(false);
        }
      }
    };
    poll();
    const timer = setInterval(poll, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, loading, error };
}
