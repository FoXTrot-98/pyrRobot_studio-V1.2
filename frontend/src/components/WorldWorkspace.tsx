// SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useRef, useState } from "react";
import { api, type WorldCatalog, type WorldPreview, type PlacementStatus } from "../api/client";
export function WorldWorkspace({running,onApplied,onBusyChange}:{running:boolean;onApplied:()=>Promise<void>;onBusyChange?:(value:boolean)=>void}) {
  const [catalog,setCatalog]=useState<WorldCatalog|null>(null);
  const [path,setPath]=useState("");
  const [values,setValues]=useState(["0","0","0","0.002","-15","-15","15","15","0.15"]);
  const [preview,setPreview]=useState<WorldPreview|null>(null);
  const [reset,setReset]=useState(false);
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState("");
  const [error,setError]=useState("");
  const [placement,setPlacement]=useState<PlacementStatus|null>(null);
  const placementToken=useRef("");
  const [checkedValues,setCheckedValues]=useState("");
  const [checkedPath,setCheckedPath]=useState("");
  const searching=placement?.search?.status==='searching';
  const currentValues=JSON.stringify([path,values]);
  useEffect(()=>{
    let active=true;
    const timer=window.setInterval(async()=>{
      const token=placementToken.current;
      if(!token)return;
      try { const result=await api.placementStatus(token);if(active&&token===placementToken.current)setPlacement(result); }
      catch(e){if(active&&token===placementToken.current){setPlacement(null);setError(String(e));}}
    },1000);
    return()=>{active=false;window.clearInterval(timer);const token=placementToken.current;placementToken.current="";if(token)void api.stopPlacement(token).catch(()=>{});};
  },[]);
  useEffect(()=>{let active=true;api.simulationWorlds().then(c=>{if(!active)return;setCatalog(c);setPath(c.configuration.webots_world??"");if(c.configuration.webots_world)setValues([...(c.configuration.spawn_pose??[0,0,0]),c.configuration.spawn_height??.002,...c.bounds,c.configuration.mapping.resolution].map(String));}).catch(e=>{if(active)setError(String(e));});return()=>{active=false;};},[]);
  const execute=async(apply:boolean)=>{
    if(!catalog)return;
    setBusy(true);onBusyChange?.(true);setError("");setMessage("");
    try {
      const nums=values.map(Number);
      const choice={path,revision:catalog.revision,spawn_pose:nums.slice(0,3),spawn_height:nums[3],bounds:nums.slice(4,8),resolution:nums[8],reset_mission:reset,source_hash:preview?.sha256??"",placement_token:placementToken.current};
      if(apply){await api.applyWorld(choice);placementToken.current="";setPlacement(null);await onApplied();setCatalog(await api.simulationWorlds());setPreview(null);setReset(false);setMessage(catalog.empty?"World saved. Open Robot setup next; startup will validate the robot's placement.":"World and checked placement applied. Start Graph, then choose Explore when sensors are ready.");}
      else {
        const result=await api.previewWorld({...choice,source_hash:""});setPreview(result);
        if(!catalog.empty){
          const check=await api.startPlacement({...choice,source_hash:result.sha256});
          placementToken.current=check.token;setCheckedValues(currentValues);setCheckedPath(path);setPlacement(check);
        }
      }
    }catch(e){setPreview(null);setError(String(e));}
    finally{setBusy(false);onBusyChange?.(false);}
  };
  const useObservedPosition=()=>{
    if(!placement?.can_use_observed||!placement.observed_position||placement.observed_yaw===undefined||checkedPath!==path)return;
    const [x,y,z]=placement.observed_position;
    setValues([String(x),String(y),String(placement.observed_yaw),String(z),...values.slice(4)]);
    setPreview(null);setError("");setMessage("Copied the safely settled Webots position. Click Check world to validate this as the starting position.");
  };
  const searchAction=async(action:'search'|'cancel')=>{
    setBusy(true);onBusyChange?.(true);setError("");
    try {setPlacement(await api.placementAction(placementToken.current,action));}
    catch(e){setError(String(e));}
    finally{setBusy(false);onBusyChange?.(false);}
  };
  const field=(label:string,i:number)=><label key={label}>{label}<input aria-label={label} type="number" step="any" value={values[i]} onChange={e=>setValues(values.map((v,j)=>j===i?e.target.value:v))}/></label>;
  return <section aria-label="Simulation worlds">
    <p>Choose an installed Webots world or a local .wbt file. Its environment is preserved and supported existing robots are replaced with your robot.</p>
    {catalog?.error&&<p role="alert">{catalog.error}</p>}
    <fieldset disabled={running||busy||!catalog} onChange={()=>{setPreview(null);setMessage("");}}>
      <label>Installed world<select aria-label="Installed world" value={catalog?.worlds.some(w=>w.path===path)?path:""} onChange={e=>setPath(e.target.value)}><option value="">Select a world or enter a path below</option>{catalog?.worlds.map(w=><option key={w.path} value={w.path}>{w.name}</option>)}</select></label>
      <label>External world path<input aria-label="External world path" value={path} onChange={e=>setPath(e.target.value)} placeholder="D:/worlds/my-world.wbt"/></label>
      <p>Path is on the computer running Studio's backend. Local assets must remain available.</p>
      <h3>Robot starting position</h3><p>Use world coordinates in metres. Height is the robot base translation. Choose a clear, level floor; (0, 0) is not necessarily inside the room.</p>
      <p>Check world opens a motor-disabled 3D preview. In Webots, select PyRobot four wheel and move it to clear floor, or edit its translation in the scene tree. Resume simulation to let it settle. Then use <strong>Use Webots position</strong> below and check again. You can also edit these coordinates directly.</p>
      <div className="world-fields">{["Spawn X (m)","Spawn Y (m)","Spawn heading (rad)","Spawn height (m)"].map((label,i)=>field(label,i))}</div>
      <details><summary>Mapping area and resolution</summary><div className="world-fields">{["Map minimum X","Map minimum Y","Map maximum X","Map maximum Y","Map resolution (m)"].map((label,i)=>field(label,i+4))}</div></details>
      <p>Mapping bounds limit exploration; they do not supply obstacles. SLAM starts with unknown cells and uses lidar observations.</p>
    </fieldset>
    <button disabled={busy||running||!catalog||!path.trim()||values.some(v=>!v.trim()||!Number.isFinite(Number(v)))} onClick={()=>execute(false)}>Check world</button>
    {preview&&<details className="world-result"><summary><strong>Compatible world structure</strong></summary><p>Replaced robot nodes: {preview.removed_robots.join(", ")||"none"}</p>{preview.warnings.map(w=><p key={w}>{w}</p>)}</details>}
    {placement&&<div className="world-result" role="status"><strong>Robot placement: {checkedValues!==currentValues?'changed — check again':placement.status}</strong>
      {placement.reasons.map(reason=><p key={reason}>{reason}</p>)}
      {placement.observed_position&&<p>Observed base XYZ: {placement.observed_position.map(v=>v.toFixed(3)).join(', ')} m</p>}
      <button disabled={busy||running||searching||placement.status==='starting'||placement.status==='failed'||checkedValues!==currentValues} onClick={()=>searchAction('search')}>Find nearby safe position</button>
      {searching&&<button disabled={busy} onClick={()=>searchAction('cancel')}>Cancel position search</button>}
      {placement.search&&<p>Position search: {placement.search.status} ({placement.search.attempt}/{placement.search.total})</p>}
      {placement.search?.status==='found'&&<p>Inspect the suggested position in Webots, then use it and check again before applying.</p>}
      {placement.search?.status==='exhausted'&&<p>No supported position found nearby. Adjust the starting X/Y or floor height and check again; this does not mean the whole world is unusable.</p>}
      <p>Search tests up to 25 nearby positions at the entered height, within mapping bounds. It moves only the preview robot; motors stay disabled. Resume Webots if paused.</p>
      <button disabled={busy||running||searching||!placement.can_use_observed||checkedPath!==path} onClick={useObservedPosition}>Use Webots position</button>
      {!placement.can_use_observed&&<p>Move the robot clear of walls and furniture, with all four wheels supported. This button becomes available once it rests safely. Resume Webots if paused.</p>}
      <p>Checks body contact, four-wheel floor support, settling and sensor readiness. This supports the current four-wheel differential-drive profile; it does not certify every terrain or robot type.</p>
    </div>}
    <label className="world-reset"><input type="checkbox" checked={reset} disabled={busy} onChange={e=>setReset(e.target.checked)}/>Reset saved maps, home and missions when applying</label>
    <button disabled={busy||running||!preview||!reset||(!catalog?.empty&&(placement?.status!=='valid'||!!placement.search||checkedValues!==currentValues))} onClick={()=>execute(true)}>Apply world</button>
    {message&&<p role="status">{message}</p>}{error&&<p role="alert">{error}</p>}
  </section>;
}
