import { useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import type { ModelLink, ModelPreview, RobotBuilderModel, Vector3 } from '../types/modelBuilder';
import { ModelViewport } from './ModelViewport';
import '../styles/model-builder.css';

const newLink=(name:string, parent:string|null, parts:string[]=[]):ModelLink=>({name,parent,parts,kind:'fixed',xyz:[0,0,0],rpy:[0,0,0],axis:[0,0,1],lower:-1.57,upper:1.57,effort:1,velocity:1,mass:null,collision:'box'});
const download=(blob:Blob,name:string)=>{const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};

export function RobotModelBuilder({initial,onClose}:{initial:RobotBuilderModel|null;onClose:(model:RobotBuilderModel|null)=>void}) {
  const dialog=useRef<HTMLDialogElement>(null);
  const [model,setModel]=useState<RobotBuilderModel|null>(initial);
  const [preview,setPreview]=useState<ModelPreview|null>(null);
  const [selected,setSelected]=useState<string[]>([]);
  const [active,setActive]=useState(initial?.links[0]?.name??'base_link');
  const [split,setSplit]=useState(true);
  const [units,setUnits]=useState(1);
  const [confirmed,setConfirmed]=useState(false);
  const [positions,setPositions]=useState<Record<string,number>>({});
  const [busy,setBusy]=useState(false);
  const [previewing,setPreviewing]=useState(false);
  const [error,setError]=useState('');
  const [previewError,setPreviewError]=useState('');
  const [report,setReport]=useState<{urdf:string;warnings:string[]}|null>(null);
  const [calibration,setCalibration]=useState('1');
  const [calibrationAxis,setCalibrationAxis]=useState(0);
  useEffect(()=>{dialog.current?.showModal();},[]);
  useEffect(()=>{
    if(!model)return;
    let cancelled=false;
    const timer=setTimeout(()=>{
      setPreviewing(true);
      api.previewModel(model,positions).then(p=>{if(!cancelled){setPreview(p);setPreviewError('');}})
        .catch(e=>{if(!cancelled)setPreviewError(String(e));}).finally(()=>{if(!cancelled)setPreviewing(false);});
    },180);
    return()=>{cancelled=true;clearTimeout(timer);};
  },[model,positions]);
  async function action(fn:()=>Promise<void>){setBusy(true);setError('');try{await fn();}catch(e){setError(String(e));}finally{setBusy(false);}}
  const change=(updated:RobotBuilderModel)=>{setModel(updated);setReport(null);};
  const link=model?.links.find(l=>l.name===active);
  const pick=(id:string)=>setSelected(values=>values.includes(id)?values.filter(v=>v!==id):[...values,id]);
  const bounds=(ids:string[])=>{
    const low=[Infinity,Infinity,Infinity],high=[-Infinity,-Infinity,-Infinity];
    for(const p of model?.parts??[])if(ids.includes(p.id))for(const v of p.vertices)for(let i=0;i<3;i++){low[i]=Math.min(low[i],v[i]*model!.scale);high[i]=Math.max(high[i],v[i]*model!.scale);}
    return {low,high,size:high.map((v,i)=>v-low[i])};
  };
  const patchLink=(updates:Partial<ModelLink>)=>{
    if(!model||!link)return;
    const renamed=updates.name??link.name;
    change({...model,links:model.links.map(l=>l.name===link.name?{...l,...updates}:l.parent===link.name?{...l,parent:renamed}:l)});
    if(updates.name!==undefined){setActive(renamed);setPositions({});}
  };
  const rescale=(scale:number)=>{
    if(!model||!Number.isFinite(scale)||scale<=0)return;
    const ratio=scale/model.scale;
    change({...model,scale,links:model.links.map(l=>({...l,xyz:l.xyz.map(v=>v*ratio) as Vector3,
      lower:l.kind==='prismatic'?l.lower*ratio:l.lower,upper:l.kind==='prismatic'?l.upper*ratio:l.upper}))});
    setPositions({});setConfirmed(false);
  };
  const addLink=(frame=false)=>{
    if(!model)return;
    let name=`${frame?'frame':'link'}_${model.links.length}`;while(model.links.some(l=>l.name===name))name+='_new';
    const item=newLink(name,active,frame?[]:selected);
    if(!frame){const b=bounds(selected);item.xyz=b.low.map((v,i)=>(v+b.high[i])/2) as Vector3;}
    change({...model,links:[...model.links.map(l=>({...l,parts:frame?l.parts:l.parts.filter(p=>!selected.includes(p)),mass:!frame&&l.parts.some(p=>selected.includes(p))?null:l.mass})),item]});
    setActive(name);setSelected([]);setPositions({});
  };
  function vector(label:string,key:'xyz'|'rpy'|'axis'){
    if(!link)return null;
    return <fieldset><legend>{label}</legend><div className="model-vector">{link[key].map((v,i)=><label key={i}>{['X','Y','Z'][i]}<input aria-label={`${label} ${['X','Y','Z'][i]}`} type="number" step=".01" value={v} onChange={e=>patchLink({[key]:link[key].map((n,j)=>j===i?Number(e.target.value):n) as Vector3})}/></label>)}</div></fieldset>;
  }
  const selectedBounds=selected.length?bounds(selected):null;
  return <dialog ref={dialog} className="model-builder" aria-label="Robot Model Builder" onCancel={e=>{e.preventDefault();if(!busy)onClose(model);}}>
    <header><h2>Robot Model Builder</h2><button disabled={busy} onClick={()=>onClose(model)}>Close</button></header>
    <p>Import OBJ → select components → create rigid links → set joints → preview → export. STEP and texture import are not supported yet. Save the editable model before leaving Studio.</p>
    <fieldset disabled={busy}><legend>Import geometry or resume a model</legend><div className="model-import">
      <label>OBJ units<select aria-label="OBJ units" value={units} onChange={e=>setUnits(Number(e.target.value))}><option value={1}>Metres</option><option value={.01}>Centimetres</option><option value={.001}>Millimetres</option></select></label>
      <label><input type="checkbox" checked={split} onChange={e=>setSplit(e.target.checked)}/>Split disconnected parts within OBJ groups</label>
      <label>Import OBJ<input aria-label="Import OBJ" type="file" accept=".obj" onChange={e=>{const f=e.target.files?.[0];e.target.value='';if(f)void action(async()=>{
        if(model&&!window.confirm('Replace this model? Save the editable model first to keep it.'))return;
        if(f.size>4*1024*1024)throw new Error('OBJ exceeds 4 MiB. Simplify it before import.');
        const imported=await api.importModelObj(await f.text(),split);imported.scale=units;
        change(imported);setActive('base_link');setSelected([]);setPositions({});setConfirmed(false);
      });}}/></label>
      <label>Open editable model<input aria-label="Open editable model" type="file" accept=".json" onChange={e=>{const f=e.target.files?.[0];e.target.value='';if(f)void action(async()=>{
        if(model&&!window.confirm('Replace this model with the saved file?'))return;
        if(f.size>12*1024*1024)throw new Error('Model exceeds 12 MiB');
        const document=await api.checkModelDocument(JSON.parse(await f.text()));
        change(document);setActive(document.links[0].name);setSelected([]);setPositions({});setConfirmed(false);
      });}}/></label>
    </div></fieldset>
    {model&&<div className="model-columns">
      <section className="model-viewport"><ModelViewport preview={preview} selected={selected} onPick={pick}/>
        <p>{previewing?'Updating preview…':previewError?'Preview is stale: correct the error below.':'Orthographic preview · lengths in metres · angles in radians'}</p>
        {previewError&&<p role="alert">{previewError}</p>}
        <fieldset disabled={busy}><legend>Scale and dimensions</legend>
          <label>Metres per OBJ unit<input type="number" min=".000000001" step=".001" value={model.scale} onChange={e=>rescale(Number(e.target.value))}/></label>
          {selectedBounds&&<p>Selection bounding box: {selectedBounds.size.map(v=>v.toFixed(5)).join(' × ')} m (source X/Y/Z)</p>}
          <label>Known selection dimension (m)<input aria-label="Known dimension" type="number" min=".000001" step=".001" value={calibration} onChange={e=>setCalibration(e.target.value)}/></label>
          <label>Measured direction<select value={calibrationAxis} onChange={e=>setCalibrationAxis(Number(e.target.value))}>{['X','Y','Z'].map((v,i)=><option key={v} value={i}>{v}</option>)}</select></label>
          <button disabled={!selectedBounds||selectedBounds.size[calibrationAxis]<=0||Number(calibration)<=0} onClick={()=>{if(selectedBounds)rescale(model.scale*Number(calibration)/selectedBounds.size[calibrationAxis]);}}>Calibrate scale</button>
          <label><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>I checked scale and the root frame orientation (+X forward, +Z up)</label>
        </fieldset>
        <fieldset><legend>Motion preview</legend><button onClick={()=>setPositions({})}>Reset to zero pose</button>
          {model.links.filter(l=>l.parent&&l.kind!=='fixed').map(l=><label key={l.name}>{l.name} · {(positions[l.name]??0).toFixed(3)} {l.kind==='prismatic'?'m':'rad'}
            <input aria-label={`${l.name} position`} type="range" min={l.kind==='continuous'?-Math.PI:l.lower} max={l.kind==='continuous'?Math.PI:l.upper} step=".001" value={positions[l.name]??0} onChange={e=>setPositions({...positions,[l.name]:Number(e.target.value)})}/></label>)}
        </fieldset>
        <fieldset disabled={busy}><legend>Save and export</legend><label>Robot name<input aria-label="Robot name" value={model.name} onChange={e=>change({...model,name:e.target.value})}/></label>
          <button onClick={()=>download(new Blob([JSON.stringify(model,null,2)],{type:'application/json'}),'robot-builder.json')}>Save editable model</button>
          <button disabled={!confirmed} onClick={()=>action(async()=>setReport(await api.validateModel(model)))}>Validate URDF</button>
          <button disabled={!confirmed} onClick={()=>action(async()=>download(await api.exportModel(model),'robot-model.zip'))}>Export URDF bundle</button>
          {report&&<><p>URDF generated. Review these limitations before physics use:</p><ul>{report.warnings.map((w,i)=><li key={i}>{w}</li>)}</ul><details><summary>Generated URDF</summary><pre>{report.urdf}</pre></details></>}
          <p>The ZIP includes robot.urdf, STL meshes and the editable model. No hardware control or simulation is started.</p>
        </fieldset>
      </section>
      <section><fieldset disabled={busy}><legend>Components ({model.parts.length})</legend><div className="model-parts">{model.parts.map(p=><label key={p.id}><input type="checkbox" checked={selected.includes(p.id)} onChange={()=>pick(p.id)}/>{p.name} <small>→ {model.links.find(l=>l.parts.includes(p.id))?.name}</small></label>)}</div>
        <button disabled={!selected.length} onClick={()=>addLink()}>Create link from selection</button>
        <button disabled={!selected.length||!link} onClick={()=>{if(link)change({...model,links:model.links.map(l=>({...l,mass:l.name===link.name||l.parts.some(p=>selected.includes(p))?null:l.mass,parts:l.name===link.name?[...new Set([...l.parts,...selected])]:l.parts.filter(p=>!selected.includes(p))}))});}}>Assign selection to active link</button>
        <button onClick={()=>setSelected([])}>Clear selection</button>
      </fieldset>
      <fieldset disabled={busy}><legend>Links and joints</legend><label>Active link<select aria-label="Active link" value={active} onChange={e=>setActive(e.target.value)}>{model.links.map(l=><option key={l.name}>{l.name}</option>)}</select></label>
        <button onClick={()=>addLink(true)}>Add empty sensor frame</button>
        {link&&<><label>Link name<input aria-label="Link name" value={link.name} onChange={e=>patchLink({name:e.target.value})}/></label>
          {link.parent!==null?<><label>Parent<select aria-label="Parent link" value={link.parent} onChange={e=>patchLink({parent:e.target.value})}>{model.links.filter(l=>l.name!==link.name).map(l=><option key={l.name}>{l.name}</option>)}</select></label>
            <label>Joint type<select aria-label="Joint type" value={link.kind} onChange={e=>{patchLink({kind:e.target.value as ModelLink['kind']});setPositions({});}}>{['fixed','continuous','revolute','prismatic'].map(v=><option key={v}>{v}</option>)}</select></label></>:<p>Root link. Its zero-pose frame becomes the exported robot origin. Set its orientation to define forward and up.</p>}
          <p>Frame origin and orientation below are in the imported model's zero-pose coordinates, converted to metres. Joint axis is in this link frame.</p>
          {vector('Pivot position (m)','xyz')}{vector('Frame roll/pitch/yaw (rad)','rpy')}{vector('Joint axis','axis')}
          <button disabled={!link.parts.length} onClick={()=>{const b=bounds(link.parts);patchLink({xyz:b.low.map((v,i)=>(v+b.high[i])/2) as Vector3});}}>Centre pivot on link geometry</button>
          {link.parent&&link.kind!=='fixed'&&<>
            {link.kind!=='continuous'&&(['lower','upper'] as const).map(k=><label key={k}>{k} ({link.kind==='prismatic'?'m':'rad'})<input type="number" step=".01" value={link[k]} onChange={e=>{patchLink({[k]:Number(e.target.value)});setPositions({});}}/></label>)}
            <label>Maximum effort (N or N·m)<input type="number" min=".001" value={link.effort} onChange={e=>patchLink({effort:Number(e.target.value)})}/></label>
            <label>Maximum speed (m/s or rad/s)<input type="number" min=".001" step=".01" value={link.velocity} onChange={e=>patchLink({velocity:Number(e.target.value)})}/></label>
          </>}
          <label>Measured mass (kg, optional)<input type="number" min=".000001" step=".01" disabled={!link.parts.length} value={link.mass??''} onChange={e=>patchLink({mass:e.target.value===''?null:Number(e.target.value)})}/></label>
          <p>If mass is entered, inertia is estimated using a uniform bounding box. This is not a measured centre of mass or CAD inertia.</p>
          <label>Collision approximation<select value={link.collision} onChange={e=>patchLink({collision:e.target.value as ModelLink['collision']})}><option value="box">Bounding box</option><option value="none">None</option></select></label>
          {link.parent&&<button onClick={()=>{if(!window.confirm('Merge this link into its parent and reparent its children?'))return;change({...model,links:model.links.filter(l=>l.name!==link.name).map(l=>({...l,parent:l.parent===link.name?link.parent:l.parent,mass:l.name===link.parent?null:l.mass,parts:l.name===link.parent?[...l.parts,...link.parts]:l.parts}))});setActive(link.parent!);setPositions({});}}>Merge link into parent</button>}
        </>}
      </fieldset></section>
    </div>}
    {error&&<p role="alert">{error}</p>}
  </dialog>;
}
