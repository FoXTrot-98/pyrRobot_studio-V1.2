// SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
// SPDX-License-Identifier: Apache-2.0

import type { Vector3 } from './modelBuilder';
export interface RobotPackage {
  robot_urdf: string;
  robot_assets: Record<string,{vertices:Vector3[];faces:number[][];normals:Vector3[];colors:Vector3[]}>;
}
export interface RobotConfiguration {
  webots_world?: string;
  webots_world_hash?: string;
  spawn_pose?: number[];
  spawn_height?: number;
  drive: {
    type: "four_wheel_differential";
    base_frame: string;
    left_joints: string[];
    right_joints: string[];
    lidar_frame: string;
    camera_frame: string;
    wheel_radius: number | null;
    collision_radius: number;
    ticks_per_turn: number;
  };
  mapping: { origin: number[]; width: number; height: number; resolution: number; inflation_radius: number };
  environment: { bounds: number[]; obstacles: number[][] };
}

export interface RobotInspection {
  name: string;
  root: string;
  links: { name: string; xyz: number[]; vertices: number[][]; faces: number[][]; normals?:Vector3[]|null; colors?:Vector3[]|null }[];
  joints: { name: string; type: string; parent: string; child: string }[];
  suggested_config: RobotConfiguration;
  warnings: string[];
}

export interface SetupDefaults {
  robot_assets: RobotPackage['robot_assets'];
  robot_urdf: string | null;
  reference_urdf: string;
  robot_config: RobotConfiguration;
  name: string;
  revision: string;
  node_count: number;
}

export interface SetupDraft {
  robot_assets?: RobotPackage['robot_assets'];
  robot_urdf: string;
  robot_config: RobotConfiguration;
  name: string;
  revision: string;
  target: "configure" | "builtin" | "webots";
  positions: Record<string, { x: number; y: number }>;
}

export interface SetupSummary {
  wheel_radius: number;
  track: number;
  mounts: Record<string, number[] | number>;
  node_count: number;
  connection_count: number;
  warnings: string[];
}
