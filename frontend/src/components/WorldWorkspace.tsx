import { useEffect, useState } from "react";
import { api, type WorldCatalog, type WorldPreview } from "../api/client";
export function WorldWorkspace({running,onApplied,onBusyChange}:{running:boolean;onApplied:()=>Promise<void>;onBusyChange?:(value:boolean)=>void}) {
  const [catalog,setCatalog]=useState<WorldCatalog|null>(null);
  const [path,setPath]=useState("");
  const [values,setValues]=useState(["0","0","0","0.002","-15","-15","15","15","0.15"]);
  const [preview,setPreview]=useState<WorldPreview|null>(null);
  const [reset,setReset]=useState(false);
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState("");
  const [error,setError]=useState("");
  useEffect(()=>{let active=true;api.simulationWorlds().then(c=>{if(!active)return;setCatalog(c);setPath(c.configuration.webots_world??"");if(c.configuration.webots_world)setValues([...(c.configuration.spawn_pose??[0,0,0]),c.configuration.spawn_height??.002,...c.bounds,c.configuration.mapping.resolution].map(String));}).catch(e=>{if(active)setError(String(e));});return()=>{active=false;};},[]);
  const execute=async(apply:boolean)=>{
    if(!catalog)return;
    setBusy(true);onBusyChange?.(true);setError("");setMessage("");
    try {
      const nums=values.map(Number);
      const choice={path,revision:catalog.revision,spawn_pose:nums.slice(0,3),spawn_height:nums[3],bounds:nums.slice(4,8),resolution:nums[8],reset_mission:reset,source_hash:preview?.sha256??""};
      if(apply){await api.applyWorld(choice);await onApplied();setCatalog(await api.simulationWorlds());setPreview(null);setReset(false);setMessage(catalog.empty?"World saved. Open Robot setup next; Webots is selected automatically.":"World applied. Start Graph, inspect the spawn in Webots, then choose Explore.");}
      else setPreview(await api.previewWorld({...choice,source_hash:""}));
    }catch(e){setPreview(null);setError(String(e));}
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
      <h3>Robot starting position</h3><p>Use world coordinates in metres. Height is the robot base translation; choose a clear, level floor. Preview checks compatibility, not spawn clearance.</p>
      <div className="world-fields">{["Spawn X (m)","Spawn Y (m)","Spawn heading (rad)","Spawn height (m)"].map((label,i)=>field(label,i))}</div>
      <details><summary>Mapping area and resolution</summary><div className="world-fields">{["Map minimum X","Map minimum Y","Map maximum X","Map maximum Y","Map resolution (m)"].map((label,i)=>field(label,i+4))}</div></details>
      <p>Mapping bounds limit exploration; they do not supply obstacles. SLAM starts with unknown cells and uses lidar observations.</p>
    </fieldset>
    <button disabled={busy||running||!catalog||!path.trim()||values.some(v=>!v.trim()||!Number.isFinite(Number(v)))} onClick={()=>execute(false)}>Check world</button>
    {preview&&<div className="world-result"><strong>Compatible world structure</strong><p>Replaced robot nodes: {preview.removed_robots.join(", ")||"none"}</p>{preview.warnings.map(w=><p key={w}>{w}</p>)}</div>}
    <label className="world-reset"><input type="checkbox" checked={reset} disabled={busy} onChange={e=>setReset(e.target.checked)}/>Reset saved maps, home and missions when applying</label>
    <button disabled={busy||running||!preview||!reset} onClick={()=>execute(true)}>Apply world</button>
    {message&&<p role="status">{message}</p>}{error&&<p role="alert">{error}</p>}
  </section>;
}
