import type { GraphState, PluginManifest, RobotInfo } from "../types";
import type { RobotInspection, SetupDefaults, SetupDraft, SetupSummary } from "../types/setup";

const BASE_URL = import.meta.env.VITE_BACKEND_URL || "http://localhost:8000";

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: init?.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail
        : Array.isArray(body.detail) ? body.detail.map((item: { loc?: unknown[]; msg?: string }) =>
          `${item.loc?.join(".") ?? "request"}: ${item.msg ?? "Invalid value"}`).join("; ")
        : detail;
    } catch {
      /* non-JSON error body, fall back to statusText */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listWebotsExamples: () => request<WebotsExample[]>("/api/examples/webots"),
  getWebotsExample: (id: string) => request<unknown>(`/api/examples/webots/${encodeURIComponent(id)}`),
  getSetup: () => request<SetupDefaults>("/api/robot/setup"),
  inspectRobot: (robot_urdf: string) => request<RobotInspection>("/api/robot/setup/inspect", {
    method: "POST", body: JSON.stringify({ robot_urdf }),
  }),
  previewSetup: (draft: SetupDraft) => request<SetupSummary>("/api/robot/setup/preview", {
    method: "POST", body: JSON.stringify(draft),
  }),
  applySetup: (draft: SetupDraft) => request<ProjectInfo>("/api/robot/setup/apply", {
    method: "POST", body: JSON.stringify(draft),
  }),
  getVizUrl: () => request<{ available: boolean; url: string | null }>("/api/viz/url"),
  listPlugins: () => request<{ plugins: PluginManifest[] }>("/api/plugins"),

  uploadUrdf: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<RobotInfo>("/api/robot/urdf", { method: "POST", body: form });
  },

  getRobotLinks: () => request<RobotInfo>("/api/robot/links"),

  getGraph: () => request<GraphState>("/api/graph"),

  addNode: (nodeId: string, pluginId: string, params: Record<string, unknown>, urdfLink?: string | null) =>
    request<GraphState>("/api/graph/nodes", {
      method: "POST",
      body: JSON.stringify({ node_id: nodeId, plugin_id: pluginId, params, urdf_link: urdfLink ?? null }),
    }),

  removeNode: (nodeId: string) => request<GraphState>(`/api/graph/nodes/${encodeURIComponent(nodeId)}`, { method: "DELETE" }),

  updateNodeParams: (nodeId: string, params: Record<string, unknown>) =>
    request<GraphState>(`/api/graph/nodes/${encodeURIComponent(nodeId)}/params`, {
      method: "PATCH",
      body: JSON.stringify({ params }),
    }),

  connect: (fromNode: string, fromPort: string, toNode: string, toPort: string) =>
    request<GraphState>("/api/graph/connections", {
      method: "POST",
      body: JSON.stringify({ from_node: fromNode, from_port: fromPort, to_node: toNode, to_port: toPort }),
    }),

  startGraph: () => request<GraphState>("/api/graph/start", { method: "POST" }),
  stopGraph: () => request<GraphState>("/api/graph/stop", { method: "POST" }),

  disconnect: (fromNode: string, fromPort: string, toNode: string, toPort: string) =>
    request<GraphState>("/api/graph/connections", {
      method: "DELETE",
      body: JSON.stringify({ from_node: fromNode, from_port: fromPort, to_node: toNode, to_port: toPort }),
    }),
  updateBinding: (nodeId: string, urdfLink: string) =>
    request<GraphState>(`/api/graph/nodes/${encodeURIComponent(nodeId)}/binding`, {
      method: "PATCH", body: JSON.stringify({ urdf_link: urdfLink }),
    }),
  getProject: () => request<ProjectInfo>("/api/project"),
  updateRobotConfig: (configuration: unknown) => request<ProjectInfo>("/api/project/robot-config", {
    method: "PATCH", body: JSON.stringify(configuration),
  }),
  exportProject: (name: string, positions: Record<string, { x: number; y: number }>) =>
    request<unknown>("/api/project/export", { method: "POST", body: JSON.stringify({ name, positions }) }),
  importProject: (document: unknown) =>
    request<ProjectInfo>("/api/project/import", { method: "POST", body: JSON.stringify(document) }),
};

export interface ProjectInfo {
  name: string;
  positions: Record<string, { x: number; y: number }>;
  robot: RobotInfo | null;
  robot_config: Record<string, unknown>;
}

export interface WebotsExample { id: string; title: string; actions: string[]; world: string }

export function busWebSocketUrl(): string {
  const wsBase = BASE_URL.replace(/^http/, "ws");
  return `${wsBase}/ws/bus`;
}

export function controlWebSocketUrl(nodeId: string, runId: string): string {
  return `${BASE_URL.replace(/^http/, "ws")}/ws/control/${encodeURIComponent(nodeId)}?run_id=${encodeURIComponent(runId)}`;
}

export { ApiError };
