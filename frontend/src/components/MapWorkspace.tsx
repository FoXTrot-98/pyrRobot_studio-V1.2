// SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useState } from "react";
import { api, type MapInfo } from "../api/client";
import { WaypointMap } from "./WaypointMap";

export function MapWorkspace({ nodeId, running }: {nodeId: string; running: boolean}) {
  const [info,setInfo]=useState<MapInfo | null>(null);
  const [name,setName]=useState("Room map");
  const [pose,setPose]=useState(["0","0","0"]);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState<string | null>(null);
  useEffect(() => {
    let active=true;
    api.getMap(nodeId).then(value => { if(active) { setError(null); setInfo(value); if(value.snapshot) setName(value.snapshot.name); } })
      .catch(e => { if(active) setError(String(e)); });
    return () => {active=false;};
  },[nodeId,running]);
  const act=async (operation: () => Promise<MapInfo>) => {
    setBusy(true);setError(null);
    try {setInfo(await operation());} catch(e) {setError(String(e));} finally {setBusy(false);}
  };
  const snapshot=info?.snapshot;
  const valid=pose.every(v => v.trim()!=="" && Number.isFinite(Number(v)));
  return <div className="map-workspace">
    <section className="control-card">
      <div className="card-heading"><h3>Map snapshot</h3><span className="state-chip">{snapshot ? "Stored in project" : "No snapshot"}</span></div>
      <p>Capture the measured map and home positions, then use <strong>Save project</strong> to download them together.</p>
      <label>Map name<input aria-label="Map name" value={name} maxLength={100} onChange={e=>setName(e.target.value)} /></label>
      <button className="primary-action" disabled={busy || !name.trim() || (!running && !info?.can_capture)} onClick={()=>act(()=>api.captureMap(nodeId,name.trim()))}>{snapshot ? "Update map snapshot" : "Capture map"}</button>
    </section>
    {error && <p role="alert" className="simulation-error">{error}</p>}
    {snapshot && <>
      <section className="control-card">
        <h3>{snapshot.name}</h3>
        <p>{snapshot.grid[0].length} by {snapshot.grid.length} cells | {snapshot.resolution} m/cell</p>
        <WaypointMap readOnly message={{topic:"saved-map",payload:{...snapshot,pose:snapshot.captured_pose},ts:{epoch_ns:0,wall_ns:0,sequence:0,source_id:"snapshot"}}} points={[]} onAdd={()=>{}} />
        <p>Snapshot preview. The marker is the pose at capture, not the robot's current location.</p>
      </section>
      <section className="control-card">
        <div className="card-heading"><h3>Start in this map</h3><span className="state-chip">{running ? "Session running" : info?.start_pose ? "Pose confirmed" : "Pose required"}</span></div>
        <p>Stop the graph and enter the robot's actual starting pose in this map. Built-in simulation starts at 0, 0, 0. Automatic relocalization is not available yet.</p>
        <div className="pose-fields">{["Start X (m)","Start Y (m)","Start yaw (rad)"].map((label,i)=><label key={label}>{label}<input aria-label={label} type="number" step="0.1" value={pose[i]} disabled={running || busy} onChange={e=>setPose(pose.map((v,j)=>i===j?e.target.value:v))}/></label>)}</div>
        <button className="primary-action" disabled={busy || running || !valid} onClick={()=>act(()=>api.initializeMap(nodeId,pose.map(Number)))}>Confirm starting pose</button>
        <p>Confirmation is required for each run. It is an operator assertion, not a verified localization result.</p>
        <button disabled={busy || running} onClick={()=>act(()=>api.clearMap(nodeId))}>Remove saved map and reset home</button>
      </section>
    </>}
    {!snapshot && <div className="map-empty"><strong>Build a map as you drive</strong><p>Start the graph, drive manually or explore, then capture the map here. Older projects work without a saved map.</p></div>}
  </div>;
}
