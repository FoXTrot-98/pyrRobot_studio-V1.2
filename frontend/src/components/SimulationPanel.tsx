import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { BusMessage } from "../types";
import { KeyboardControl } from "./KeyboardControl";
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
      await onUpdate(nodeId, points ? { waypoints: points, enabled: true } : { waypoints: [], goal_x: Number(goalX), goal_y: Number(goalY), enabled: true });
      if (selector) await onUpdate(selector.id, { mode: "autonomous" });
      setDraftWaypoints(null);
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

  return <section className="simulation-panel raised" aria-label="Robot simulation">
    <div className="simulation-controls">
      <strong>Robot simulation</strong>
      <label>Goal X <input aria-label="Goal X" type="number" step={.1} value={goalX} onChange={(e) => setGoalX(e.target.value)} /></label>
      <label>Y <input aria-label="Goal Y" type="number" step={.1} value={goalY} onChange={(e) => setGoalY(e.target.value)} /></label>
      <button disabled={busy || !valid} onClick={() => navigate()}>Navigate</button>
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
        {teleopId && <KeyboardControl nodeId={teleopId} runId={runId} active={running && selector?.mode === "manual"} />}
        <strong>SLAM waypoints</strong>
        <p>Click free or unknown map cells to queue destinations. Black cells are obstacles.</p>
        {current?.status === "no_path" && <p role="status">No clear route. Choose a point farther from walls or explore more of the room in Manual mode.</p>}
        {current?.status === "obstacle_stop" && <p role="status">An obstacle is too close. Motion is stopped while the map and route update.</p>}
        {current?.status === "sensor_timeout" && <p role="status">Waiting for fresh sensor data. Motion resumes when mapping updates return.</p>}
        {current?.status === "mission_complete" && <p role="status">All waypoints reached. Add a new mission to continue.</p>}
        <WaypointMap message={map?.run_id === runId ? map : undefined} points={waypoints} path={current?.points}
          onAdd={(point) => { if (waypoints.length < 100) setDraftWaypoints([...waypoints, point]); }} />
        <div>{waypoints.length} waypoints{typeof current?.waypoint_index === "number" && waypoints.length > 0 ? ` · current ${current.waypoint_index + 1}` : ""}</div>
        <button disabled={busy || !waypoints.length} onClick={() => navigate(waypoints)}>Run waypoints</button>
        <button disabled={!waypoints.length || busy} onClick={() => setDraftWaypoints(waypoints.slice(0, -1))}>Undo point</button>
        <button disabled={busy} onClick={async () => {
          await selectMode("stopped");
          await change({ waypoints: [], enabled: false });
          setDraftWaypoints([]);
        }}>Clear waypoints</button>
        {waypoints.length > 0 && <ol>{waypoints.map((p, i) => <li key={i}>{p[0].toFixed(2)}, {p[1].toFixed(2)} m</li>)}</ol>}
      </aside>
    </div>
  </section>;
}
