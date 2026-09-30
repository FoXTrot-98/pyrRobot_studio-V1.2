import type { GraphState, PluginManifest, RobotInfo } from "../types";
import type { RobotInspection, RobotPackage, SetupDefaults, SetupDraft, SetupSummary } from "../types/setup";
import type { ModelPreview, RobotBuilderModel } from "../types/modelBuilder";

const BASE_URL = import.meta.env.VITE_BACKEND_URL || "http://localhost:8000";
let studioToken = "";
export function setStudioToken(token: string) { studioToken = token; }
export function studioSocketProtocols() {
  return studioToken ? ["pyrobot", "auth." + btoa(studioToken).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "")] : [];
}

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit, binary = false): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: { ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(studioToken ? { Authorization: `Bearer ${studioToken}` } : {}), ...init?.headers },
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
  return (binary ? res.blob() : res.json()) as Promise<T>;
}

export interface MapInfo {
  snapshot: { name: string; grid: number[][]; origin: number[]; resolution: number; captured_pose: number[]; home_poses: Record<string,number[]> } | null;
  start_pose: number[] | null;
  can_capture: boolean;
}

export interface WorldChoice { path:string; revision:string; spawn_pose:number[]; spawn_height:number; bounds:number[]; resolution:number; reset_mission:boolean; source_hash?:string }
export interface WorldPreview { path:string; sha256:string; removed_robots:string[]; warnings:string[] }
export interface WorldCatalog { worlds:{path:string;name:string}[]; error:string|null; revision:string; configuration:import('../types/setup').RobotConfiguration; bounds:number[]; empty:boolean }
export const api = {
  simulationWorlds: () => request<WorldCatalog>('/api/simulation/worlds'),
  previewWorld: (choice:WorldChoice) => request<WorldPreview>('/api/simulation/worlds/preview',{method:'POST',body:JSON.stringify(choice)}),
  applyWorld: (choice:WorldChoice) => request<unknown>('/api/simulation/worlds/apply',{method:'POST',body:JSON.stringify(choice)}),
  getMap: (nodeId: string) => request<MapInfo>(`/api/project/maps/${encodeURIComponent(nodeId)}`),
  captureMap: (nodeId: string, name: string) => request<MapInfo>(`/api/project/maps/${encodeURIComponent(nodeId)}`, {method:"POST",body:JSON.stringify({name})}),
  initializeMap: (nodeId: string, pose: number[]) => request<MapInfo>(`/api/project/maps/${encodeURIComponent(nodeId)}/initialize`, {method:"POST",body:JSON.stringify({pose})}),
  clearMap: (nodeId: string) => request<MapInfo>(`/api/project/maps/${encodeURIComponent(nodeId)}`, {method:"DELETE"}),
  modelSetup: (model:RobotBuilderModel) => request<RobotPackage>('/api/model-builder/setup',{method:'POST',body:JSON.stringify(model)}),
  importBuilderBundle: (file:File) => {const form=new FormData();form.append('file',file);return request<RobotPackage>('/api/robot/setup/bundle',{method:'POST',body:form});},
  importModelObj: (text:string, split:boolean) => request<RobotBuilderModel>('/api/model-builder/import-obj',{method:'POST',body:JSON.stringify({text,split})}),
  importModelStep: (file:File, deflection=0.5, angle=0.5) => {const form=new FormData();form.append('file',file);return request<RobotBuilderModel>(`/api/model-builder/import-step?deflection=${encodeURIComponent(deflection)}&angle=${encodeURIComponent(angle)}`,{method:'POST',body:form});},
  checkModelDocument: (model:unknown) => request<RobotBuilderModel>('/api/model-builder/document',{method:'POST',body:JSON.stringify(model)}),
  previewModel: (model:RobotBuilderModel, positions:Record<string,number>) => request<ModelPreview>('/api/model-builder/preview',{method:'POST',body:JSON.stringify({model,positions})}),
  validateModel: (model:RobotBuilderModel) => request<{urdf:string;warnings:string[]}>('/api/model-builder/validate',{method:'POST',body:JSON.stringify(model)}),
  exportModel: (model:RobotBuilderModel) => request<Blob>('/api/model-builder/export',{method:'POST',body:JSON.stringify(model)},true),
  builderCatalog: () => request<{ schemas: Record<string, unknown>; types: string[] }>("/api/plugin-builder/catalog"),
  builderGenerate: (draft: unknown) => request<{source: string}>("/api/plugin-builder/generate", {method:"POST",body:JSON.stringify(draft)}),
  builderTest: (source: string, sample: unknown) => request<BuilderTest>("/api/plugin-builder/tests", {method:"POST",body:JSON.stringify({source,sample,trusted:true})}),
  builderTestStatus: (id: string) => request<BuilderTest>(`/api/plugin-builder/tests/${id}`),
  builderCancel: (id: string) => request<BuilderTest>(`/api/plugin-builder/tests/${id}`, {method:"DELETE"}),
  builderInstall: (id: string) => request<{path: string; restart_required: boolean}>(`/api/plugin-builder/tests/${id}/install`, {method:"POST"}),
  listWebotsExamples: () => request<WebotsExample[]>("/api/examples/webots"),
  getWebotsExample: (id: string) => request<unknown>(`/api/examples/webots/${encodeURIComponent(id)}`),
  getSetup: () => request<SetupDefaults>("/api/robot/setup"),
  inspectRobot: (robot_urdf: string, robot_assets:RobotPackage['robot_assets']={}) => request<RobotInspection>("/api/robot/setup/inspect", {
    method: "POST", body: JSON.stringify({ robot_urdf, robot_assets }),
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
export interface BuilderTest { id: string; status: string; result?: {ok: boolean; error?: string; manifest?: PluginManifest; outputs?: unknown[]; logs?: string[]} }

export function busWebSocketUrl(): string {
  const wsBase = BASE_URL.replace(/^http/, "ws");
  return `${wsBase}/ws/bus?preview=true`;
}

export function controlWebSocketUrl(nodeId: string, runId: string): string {
  return `${BASE_URL.replace(/^http/, "ws")}/ws/control/${encodeURIComponent(nodeId)}?run_id=${encodeURIComponent(runId)}`;
}

export { ApiError };
