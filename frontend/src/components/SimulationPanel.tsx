// SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { BusMessage } from "../types";
import { KeyboardControl } from "./KeyboardControl";
import { MapWorkspace } from "./MapWorkspace";
import { WaypointMap } from "./WaypointMap";

interface Props {
  nodeId: string;
  params: Record<string, unknown>;
  running: boolean;
  runId: string | null;
  status?: BusMessage;
  map?: BusMessage;
  teleopId?: string;
  selector?: { id: string; mode: string };
  onUpdate: (nodeId: string, params: Record<string, unknown>) => Promise<void>;
}

export function SimulationPanel({ nodeId, params, running, runId, status, map, teleopId, selector, onUpdate }: Props) {
  const [tab, setTab] = useState<"navigate" | "maps" | "settings">("navigate");
  const [viewerUrl, setViewerUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [goalX, setGoalX] = useState(String(params.goal_x ?? 8));
  const [goalY, setGoalY] = useState(String(params.goal_y ?? 6));
  const [busy, setBusy] = useState(false);
  const [configuration, setConfiguration] = useState<string | null>(null);
  const [draftWaypoints, setDraftWaypoints] = useState<number[][] | null>(null);
  const waypoints = draftWaypoints ?? (params.waypoints as number[][] | undefined) ?? [];

  const driveMode = async (mode: string) => {
    await onUpdate(nodeId, { enabled: mode === "autonomous" });
    if (selector) await onUpdate(selector.id, { mode });
  };
  const selectMode = async (mode: string) => {
    setBusy(true);
    try { await driveMode(mode); setError(null); }
    catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };
  const navigate = async (points?: number[][]) => {
    setBusy(true);
    try {
      await onUpdate(nodeId, points ? { waypoints: points, enabled: true, explore: false, return_home: false } : { waypoints: [], explore: false, return_home: false, goal_x: Number(goalX), goal_y: Number(goalY), enabled: true });
      if (selector) await onUpdate(selector.id, { mode: "autonomous" });
      setDraftWaypoints(null);
      setError(null);
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };

  const returnHome = async () => {
    setBusy(true);
    try {
      await onUpdate(nodeId, { explore: false, return_home: true, enabled: true });
      if (selector) await onUpdate(selector.id, { mode: "autonomous" });
      setError(null);
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };

  const editConfiguration = async () => {
    try {
      const project = await api.getProject();
      setConfiguration(JSON.stringify(project.robot_config, null, 2));
    } catch (e) { setError(String(e)); }
  };
  const saveConfiguration = async () => {
    setBusy(true);
    try {
      await api.updateRobotConfig(JSON.parse(configuration ?? "{}"));
      setConfiguration(null);
      setError(null);
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };

  useEffect(() => {
    let cancelled = false;
    api.getVizUrl().then((result) => {
      if (cancelled) return;
      setViewerUrl(result.available ? result.url : null);
      if (!result.available) setError("Rerun is unavailable. Check the backend terminal and restart the backend.");
    }).catch((e) => { if (!cancelled) setError(String(e)); });
    return () => { cancelled = true; };
  }, []);

  const change = async (updates: Record<string, unknown>) => {
    setBusy(true);
    try { await onUpdate(nodeId, updates); setError(null); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const x = Number(goalX), y = Number(goalY);
  const valid = goalX.trim() !== "" && goalY.trim() !== "" && Number.isFinite(x) && Number.isFinite(y);
  const current = status?.run_id === runId ? status?.payload : undefined;

  const home = current?.home_pose as number[] | undefined;
  const canSetHome = running && Array.isArray(current?.pose) && current?.status !== "sensor_timeout";

  return <section className="simulation-panel" aria-label="Robot simulation">
    <div className="simulation-controls">
      <strong>Robot simulation</strong>
      <button disabled={busy} onClick={() => selector ? selectMode(selector.mode === "stopped" ? "autonomous" : "stopped") : change({ enabled: !params.enabled })}>{(selector ? selector.mode !== "stopped" : params.enabled) ? "Pause motion" : "Resume motion"}</button>
      <span className="simulation-status">{!running ? "Stopped — Start Graph to simulate" : String(current?.status ?? "Starting sensors…").replaceAll("_", " ")}
        {running && typeof current?.distance_to_goal === "number" && ` · ${current.distance_to_goal.toFixed(2)} m to goal`}</span>
      {viewerUrl && <a href={viewerUrl} target="_blank" rel="noreferrer">Open Rerun ↗</a>}
      <button disabled={running || busy} onClick={editConfiguration}>Robot configuration</button>
    </div>
    {configuration !== null && <div aria-label="Robot configuration editor" style={{ padding: 12 }}>
      <p>Wheel joints, sensor frames, room bounds and map settings. Stop the graph to apply changes; Save project includes these settings.</p>
      <textarea aria-label="Robot configuration JSON" value={configuration} disabled={running || busy}
        onChange={(e) => setConfiguration(e.target.value)} style={{ width: "100%", height: 220, fontFamily: "monospace" }} />
      <button disabled={running || busy} onClick={saveConfiguration}>Apply configuration</button>
      <button onClick={() => setConfiguration(null)}>Cancel</button>
    </div>}
    {error && <div role="alert" className="simulation-error">{error}</div>}
    <div className="simulation-views">
      {viewerUrl ? <iframe src={viewerUrl} title="Rerun robot simulation" allow="fullscreen" /> : <p>Connecting to the Rerun viewer…</p>}
      <aside className="navigation-controls" aria-label="Map and robot controls">
        {selector && <div className="drive-modes">
          <button aria-pressed={selector.mode === "manual"} disabled={busy} onClick={() => selectMode("manual")}>Manual</button>
          <button aria-pressed={selector.mode === "autonomous"} disabled={busy} onClick={() => selectMode("autonomous")}>Autonomous</button>
          <button disabled={busy} onClick={() => selectMode("stopped")}>Stop</button>
        </div>}
        {teleopId && <div hidden={selector?.mode !== "manual"}><KeyboardControl nodeId={teleopId} runId={runId} active={running && selector?.mode === "manual"} /></div>}
        <div className="simulation-tabs" role="tablist" aria-label="Simulation tools">
          {(["navigate","maps","settings"] as const).map(value=><button key={value} role="tab" aria-selected={tab===value} onClick={()=>setTab(value)}>{value[0].toUpperCase()+value.slice(1)}</button>)}
        </div>
        {tab === "maps" && <div role="tabpanel" aria-label="Maps"><MapWorkspace nodeId={nodeId} running={running}/></div>}
        {tab === "settings" && <section role="tabpanel" aria-label="Settings" className="control-card">
        <h3>Navigation algorithms</h3>
        <label>Planner <select aria-label="Planner" disabled={busy} value={String(params.planner ?? "astar")} onChange={(e) => change({ planner: e.target.value })}>
          <option value="astar">A*</option><option value="dijkstra">Dijkstra (experimental)</option>
        </select></label>
        <label>Controller <select aria-label="Controller" disabled={busy} value={String(params.controller ?? "proportional")} onChange={(e) => change({ controller: e.target.value })}>
          <option value="proportional">Proportional</option><option value="fuzzy">Fuzzy logic (experimental)</option>
        </select></label>
        <p>Changing algorithms stops motion until a fresh map update replans the current mission.</p>
        </section>}
        <div role="tabpanel" aria-label="Navigate" hidden={tab!=="navigate"}>
        <section className="control-card">
        <h3>Mission</h3>
        <div className="goal-fields">
      <label>Goal X <input aria-label="Goal X" type="number" step={.1} value={goalX} onChange={(e) => setGoalX(e.target.value)} /></label>
      <label>Y <input aria-label="Goal Y" type="number" step={.1} value={goalY} onChange={(e) => setGoalY(e.target.value)} /></label>
      <button disabled={busy || !valid} onClick={() => navigate()}>Navigate</button>
        </div>
        <p>{String(current?.mission_type ?? "goal").replaceAll("_", " ")}: {String(current?.mission_state ?? "waiting for graph").replaceAll("_", " ")}</p>
        <button disabled={busy || !running || current?.mission_state === "cancelled"} onClick={() => change({ cancel_mission: true })}>Cancel mission</button>
        {current?.mission_state === "cancelled" && <p role="status">Mission cancelled. Choose Navigate, Run waypoints, Explore map or Return home to start a new mission.</p>}
        </section><section className="control-card">
        <h3>Home position</h3>
        <p>{home ? `Home: ${home[0].toFixed(2)}, ${home[1].toFixed(2)} m` : "Home is captured from the first map pose of this run."}</p>
        <button disabled={busy || !canSetHome} onClick={() => change({ home_pose: current?.pose, explore: false, return_home: false, enabled: false })}>Set home here</button>
        <button disabled={busy || !running || !home} onClick={returnHome}>Return home</button>
        <p>Set home here pauses navigation and saves the position with the project. Use it only in the same map.</p>
        {current?.status === "home_reached" && <p role="status">Home reached. Robot stopped; this does not perform docking.</p>}
        {current?.status === "aligning_home" && <p role="status">At home position; turning to the saved heading.</p>}
        </section><section className="control-card">
        <h3>Exploration</h3>
        <button disabled={busy || !running} onClick={async () => {
          setBusy(true);
          try {
            await onUpdate(nodeId, { explore: true, return_home: false, enabled: true });
            if (selector) await onUpdate(selector.id, { mode: "autonomous" });
            setError(null);
          } catch (e) { setError(String(e)); }
          finally { setBusy(false); }
        }}>Explore map</button>
        <p>Visits reachable frontiers, then returns home after {String(params.exploration_targets ?? 20)} targets or when no eligible frontiers remain. Pause motion pauses exploration.</p>
        {current?.exploring === true && <p role="status">Exploration: {String(current.exploration_targets)} targets selected. {String(current.reason ?? "")}</p>}
        </section><section className="control-card">
        <h3>SLAM waypoints</h3>
        <p>Click free or unknown map cells to queue destinations. Black cells are obstacles.</p>
        {current?.status === "no_path" && <p role="status">{String(current.reason ?? "No clear route. Choose a point farther from walls or explore more of the room in Manual mode.")}</p>}
        {current?.status === "obstacle_stop" && <p role="status">An obstacle is too close. Motion is stopped while the map and route update.</p>}
        {current?.status === "sensor_timeout" && <p role="status">Waiting for fresh sensor data. Motion resumes when mapping updates return.</p>}
        {(current?.status === "stalled" || current?.status === "navigation_failed") && <div role="alert">
          <p>{String(current.reason ?? "Navigation stopped. Check the robot and route before retrying.")}</p>
          <button disabled={busy || !running} onClick={() => change({ enabled: true })}>Retry navigation</button>
        </div>}
        {current?.status === "replanning" && <p role="status">Stopped while waiting for a fresh observation and route.</p>}
        {current?.status === "mission_complete" && <p role="status">All waypoints reached. Add a new mission to continue.</p>}
        <WaypointMap message={map?.run_id === runId ? map : undefined} points={waypoints} path={current?.points}
          onAdd={(point) => { if (waypoints.length < 100) setDraftWaypoints([...waypoints, point]); }} />
        <div>{waypoints.length} waypoints{typeof current?.waypoint_index === "number" && waypoints.length > 0 ? ` · current ${current.waypoint_index + 1}` : ""}</div>
        <button disabled={busy || !waypoints.length} onClick={() => navigate(waypoints)}>Run waypoints</button>
        <button disabled={!waypoints.length || busy} onClick={() => setDraftWaypoints(waypoints.slice(0, -1))}>Undo point</button>
        <button disabled={busy} onClick={async () => {
          await selectMode("stopped");
          await change({ waypoints: [], enabled: false, explore: false, return_home: false });
          setDraftWaypoints([]);
        }}>Clear waypoints</button>
        {waypoints.length > 0 && <ol>{waypoints.map((p, i) => <li key={i}>{p[0].toFixed(2)}, {p[1].toFixed(2)} m</li>)}</ol>}
        </section></div>
      </aside>
    </div>
  </section>;
}
