// SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
// SPDX-License-Identifier: Apache-2.0

export type PortDataType =
  | "image" | "pointcloud" | "pose" | "imu" | "string" | "number" | "bool" | "json" | "any";

export interface PortSpec {
  name: string;
  data_type: PortDataType;
  required: boolean;
  description: string;
  schema?: string | null;
}

export interface ParamSpec {
  name: string;
  kind: "number" | "string" | "bool" | "enum" | "file" | "json";
  default: unknown;
  min?: number | null;
  max?: number | null;
  options?: string[] | null;
  description: string;
}

export interface PluginManifest {
  id: string;
  name: string;
  category: string;
  version: string;
  author: string;
  description: string;
  icon?: string | null;
  inputs: PortSpec[];
  outputs: PortSpec[];
  params: ParamSpec[];
  requires_urdf_link: boolean;
}

export interface GraphNode {
  node_id: string;
  plugin_id: string;
  params: Record<string, unknown>;
  urdf_link: string | null;
  state: string;
  error: string | null;
  /** canvas position — the backend doesn't track this; the frontend layer persists it locally */
  position?: { x: number; y: number };
}

export interface GraphConnection {
  from_node: string;
  from_port: string;
  to_node: string;
  to_port: string;
}

export interface GraphState {
  running: boolean;
  failure_reason?: string | null;
  run_id?: string | null;
  nodes: GraphNode[];
  connections: GraphConnection[];
}

export interface RobotInfo {
  name: string;
  links: string[];
  joint_count?: number;
}

export interface PRTTimestamp {
  epoch_ns: number;
  wall_ns: number;
  sequence: number;
  source_id: string;
}

export interface BusMessage {
  topic: string;
  payload: Record<string, unknown>;
  ts: PRTTimestamp;
  published_ts?: PRTTimestamp;
  clock_domain?: string;
  schema?: string | null;
  run_id?: string | null;
}
