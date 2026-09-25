import { useEffect, useRef, useState } from "react";
import { api, type BuilderTest } from "../api/client";
import "../styles/plugin-builder.css";
import { DRAFT_KEY, loadPluginDraft, parsePluginDraft, type BuilderPort as Port, type BuilderParameter as Parameter } from "../utils/pluginDraft";

const initialPort = (name: string): Port => ({name,data_type:"json",schema:null,required:true});

export function PluginBuilder({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [saved] = useState(loadPluginDraft);
  const [slug,setSlug] = useState(saved?.slug ?? "my_processor");
  const [name,setName] = useState(saved?.name ?? "My processor");
  const [version,setVersion] = useState(saved?.version ?? "0.1.0");
  const [description,setDescription] = useState(saved?.description ?? "");
  const [template,setTemplate] = useState(saved?.template ?? "processing");
  const [inputs,setInputs] = useState<Port[]>(saved?.inputs ?? [initialPort("input")]);
  const [outputs,setOutputs] = useState<Port[]>(saved?.outputs ?? [initialPort("output")]);
  const [params,setParams] = useState<Parameter[]>(saved?.params ?? []);
  const [sample,setSample] = useState(saved?.sample ?? '{"value": 1}');
  const [source,setSource] = useState(saved?.source ?? "");
  const [catalog,setCatalog] = useState<{schemas:Record<string,unknown>;types:string[]}>({schemas:{},types:[]});
  const [trusted,setTrusted] = useState(false);
  const [test,setTest] = useState<BuilderTest | null>(null);
  const [testedSource,setTestedSource] = useState("");
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState("");
  const [notice,setNotice] = useState("");
  const [dirty,setDirty] = useState(saved?.dirty ?? false);
  const [draftStatus,setDraftStatus] = useState("");
  useEffect(() => {
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify(parsePluginDraft({slug,name,version,description,template,inputs,outputs,params,sample,source,dirty})));
      setDraftStatus("Draft saved in this browser. Trust and test results are not saved.");
    } catch { setDraftStatus("Draft could not be saved in this browser. Export a package to keep your work."); }
  }, [slug,name,version,description,template,inputs,outputs,params,sample,source,dirty]);
  const upload = useRef<HTMLInputElement>(null);
  const running = test?.status === "running";
  useEffect(() => { dialog.current?.showModal(); api.builderCatalog().then(setCatalog).catch(e=>setError(String(e))); }, []);
  useEffect(() => {
    if (!test || test.status !== "running") return;
    let cancelled = false;
    const timer = setInterval(() => api.builderTestStatus(test.id).then(value => {if(!cancelled)setTest(value);}).catch(e=>{if(!cancelled)setError(String(e));}), 300);
    return () => { cancelled=true; clearInterval(timer); };
  }, [test]);
  async function action(fn:()=>Promise<void>) {
    setBusy(true);setError("");setNotice("");
    try {await fn();} catch(e){setError(String(e));} finally{setBusy(false);}
  }
  const changed = () => {setDirty(true);setNotice("");};
  function portEditor(title:string, ports:Port[], update:(p:Port[])=>void) {
    return <fieldset><legend>{title}</legend>{ports.map((port,index)=><div className="builder-port" key={index}>
      <label>Name<input aria-label={`${title} ${index+1} name`} value={port.name} onChange={e=>{update(ports.map((p,i)=>i===index?{...p,name:e.target.value}:p));changed();}} /></label>
      <label>Type<select value={port.data_type} onChange={e=>{update(ports.map((p,i)=>i===index?{...p,data_type:e.target.value}:p));changed();}}>{catalog.types.map(t=><option key={t}>{t}</option>)}</select></label>
      <label>Message schema<select aria-label={`${title} ${index+1} schema`} value={port.schema??""} onChange={e=>{update(ports.map((p,i)=>i===index?{...p,schema:e.target.value||null,data_type:e.target.value.endsWith('/Image@1')?'image':p.data_type}:p));changed();}}>
        <option value="">Untyped payload</option>{Object.keys(catalog.schemas).map(s=><option key={s}>{s}</option>)}</select></label>
      {title==="Inputs"&&<label><input type="checkbox" checked={port.required} onChange={e=>{update(ports.map((p,i)=>i===index?{...p,required:e.target.checked}:p));changed();}}/>Required</label>}
      <button onClick={()=>{update(ports.filter((_,i)=>i!==index));changed();}}>Remove</button>
      {port.schema&&<details><summary>Schema fields and units</summary><pre>{JSON.stringify(catalog.schemas[port.schema],null,2)}</pre></details>}
    </div>)}<button disabled={ports.length>=16} onClick={()=>{update([...ports,initialPort(`port_${ports.length+1}`)]);changed();}}>Add {title.toLowerCase().slice(0,-1)}</button></fieldset>;
  }
  return <dialog className="plugin-builder" ref={dialog} aria-label="Plugin Builder" onCancel={event=>{event.preventDefault();if(!running&&!busy)onClose();}}>
    <header><h2>Plugin Builder</h2><button disabled={busy||running} onClick={onClose}>Close</button></header>
    <p>{draftStatus}</p>
    <button disabled={busy||running} onClick={()=>{
      if(!window.confirm('Start a new draft? Export your current work first to keep a separate copy.'))return;
      setSlug('my_processor');setName('My processor');setVersion('0.1.0');setDescription('');setTemplate('processing');
      setInputs([initialPort('input')]);setOutputs([initialPort('output')]);setParams([]);setSample('{"value": 1}');setSource('');
      setDirty(false);setTest(null);setTrusted(false);setTestedSource('');setError('');setNotice('');
    }}>New draft</button>
    <p>Create a sensor source or processing node, edit its Python, then test with sample messages. Sensor templates initially emit sample data; they do not connect to hardware.</p>
    <div className="builder-columns">
      <section aria-label="Plugin definition"><fieldset disabled={busy||running} onChange={changed}><legend>1. Describe your plugin</legend>
        <label>Template<select aria-label="Plugin template" value={template} onChange={e=>{setTemplate(e.target.value);setInputs(e.target.value==="sensor"?[]:[initialPort("input")]);}}><option value="processing">Processing</option><option value="sensor">Sensor source</option></select></label>
        <label>Plugin ID: user.<input aria-label="Plugin slug" value={slug} onChange={e=>setSlug(e.target.value)} /></label>
        <label>Display name<input aria-label="Plugin display name" value={name} onChange={e=>setName(e.target.value)} /></label>
        <label>Version<input value={version} onChange={e=>setVersion(e.target.value)} /></label>
        <label>Description<input value={description} onChange={e=>setDescription(e.target.value)} /></label>
      </fieldset>
      <fieldset disabled={busy||running}><legend>2. Ports and settings</legend>
        {template==="processing"&&portEditor("Inputs",inputs,setInputs)}
        {portEditor("Outputs",outputs,setOutputs)}
        <fieldset><legend>Parameters</legend>{params.map((p,index)=><div className="builder-port" key={index}>
          <label>Name<input value={p.name} onChange={e=>{setParams(params.map((v,i)=>i===index?{...v,name:e.target.value}:v));changed();}} /></label>
          <label>Kind<select value={p.kind} onChange={e=>{setParams(params.map((v,i)=>i===index?{...v,kind:e.target.value,value:e.target.value==='bool'?'false':e.target.value==='json'?'{}':'1'}:v));changed();}}>{['number','string','bool','json'].map(k=><option key={k}>{k}</option>)}</select></label>
          <label>Default<input value={p.value} onChange={e=>{setParams(params.map((v,i)=>i===index?{...v,value:e.target.value}:v));changed();}} /></label>
          {p.kind==='number'&&(['min','max'] as const).map(bound=><label key={bound}>{bound}<input type="number" value={p[bound]} onChange={e=>{setParams(params.map((v,i)=>i===index?{...v,[bound]:e.target.value}:v));changed();}} /></label>)}
          <button onClick={()=>{setParams(params.filter((_,i)=>i!==index));changed();}}>Remove parameter</button>
        </div>)}<button disabled={params.length>=32} onClick={()=>{setParams([...params,{name:`setting_${params.length+1}`,kind:'number',value:'1',min:'',max:''}]);changed();}}>Add parameter</button></fieldset>
      </fieldset>
      <button disabled={busy||running} onClick={()=>action(async()=>{
        if(source&&!window.confirm('Regenerate Python from the form? This replaces code edits.'))return;
        const result=await api.builderGenerate({slug,name,version,description,template,inputs,outputs,sample:JSON.parse(sample),params:params.map(p=>({name:p.name,kind:p.kind,default:p.kind==='string'?p.value:JSON.parse(p.value),min:p.min===''?null:Number(p.min),max:p.max===''?null:Number(p.max)}))});
        setSource(result.source);setTest(null);setDirty(false);
      })}>Generate Python</button>
      </section>
      <section aria-label="Plugin code and testing"><h3>3. Edit and test</h3>
        {dirty&&source&&<p>Form settings changed. Regenerate to apply them to Python. Tests and exports use the Python shown below.</p>}
        <label>Python source<textarea className="builder-code" aria-label="Python source" spellCheck={false} value={source} disabled={busy||running} onChange={e=>{setSource(e.target.value);setNotice('');}} /></label>
        <label>Sample payload (JSON, sent to each input)<textarea aria-label="Sample payload" value={sample} disabled={busy||running} onChange={e=>{setSample(e.target.value);setTest(null);}} /></label>
        <label><input type="checkbox" checked={trusted} disabled={busy||running} onChange={e=>setTrusted(e.target.checked)}/>I trust this Python code. Testing can access this computer's files, network and devices.</label>
        <p>Tests run in a separate process for up to eight seconds, with captured outputs and logs. This is not a security sandbox or hardware qualification.</p>
        <button disabled={!source||!trusted||busy||running} onClick={()=>action(async()=>{setTest(await api.builderTest(source,JSON.parse(sample)));setTestedSource(source);})}>Test plugin</button>
        <button disabled={!running||busy} onClick={()=>action(async()=>{if(test)setTest(await api.builderCancel(test.id));})}>Cancel test</button>
        {test&&<div role="status"><strong>Test: {test.status}</strong>
          {test.status==='passed'&&source!==testedSource&&<p>Python changed since this test. Test again before installing.</p>}
          {test.result?.error&&<pre role="alert">{test.result.error}</pre>}
          {test.result?.manifest&&<p>Tested plugin: {test.result.manifest.name} · {test.result.manifest.id} · v{test.result.manifest.version}</p>}
          {!!test.result?.outputs?.length&&<details open><summary>Output messages ({test.result.outputs.length})</summary><pre>{JSON.stringify(test.result.outputs,null,2)}</pre></details>}
          {!!test.result?.logs?.length&&<details open><summary>Test logs</summary><pre>{test.result.logs.join('\n')}</pre></details>}
          {test.result&&<details><summary>Full test report</summary><pre>{JSON.stringify(test.result,null,2)}</pre></details>}
        </div>}
        <h3>4. Export or install</h3>
        <button disabled={!source||busy||running} onClick={()=>action(async()=>{
          const url=URL.createObjectURL(new Blob([JSON.stringify({format:'pyrobot-plugin-source',version:2,source,sample:JSON.parse(sample),draft:{slug,name,version,description,template,inputs,outputs,params,sample,source,dirty}},null,2)],{type:'application/json'}));
          const a=document.createElement('a');a.href=url;a.download=`${slug.replace(/[^a-z0-9_]/g,'_')}.pyrobot-plugin.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
        })}>Export package</button>
        <button disabled={busy||running} onClick={()=>upload.current?.click()}>Import package</button>
        <input ref={upload} hidden type="file" accept=".json" onChange={e=>{const file=e.target.files?.[0];e.target.value='';if(file)void action(async()=>{
          if(file.size>500000)throw new Error('Package exceeds 500 KB');
          const pkg=JSON.parse(await file.text());if(pkg.format!=='pyrobot-plugin-source'||![1,2].includes(pkg.version)||typeof pkg.source!=='string')throw new Error('Invalid plugin source package');
          if(pkg.version===2){
            const d=parsePluginDraft(pkg.draft);
            if(d.source!==pkg.source||JSON.stringify(JSON.parse(d.sample))!==JSON.stringify(pkg.sample))throw new Error('Package source/sample disagrees with its draft');
            setSlug(d.slug);setName(d.name);setVersion(d.version);setDescription(d.description);setTemplate(d.template);
            setInputs(d.inputs);setOutputs(d.outputs);setParams(d.params);setSource(d.source);setSample(d.sample);setDirty(d.dirty);
            setTest(null);setTrusted(false);setNotice('Imported form, Python and sample. Review and test before installing.');return;
          }
          setSource(pkg.source);setSample(JSON.stringify(pkg.sample??{},null,2));setTest(null);setTrusted(false);setDirty(true);setNotice('Imported Python and sample. The form is not reconstructed; edit the imported Python directly.');
        });}} />
        <button disabled={busy||running||!trusted||test?.status!=='passed'||source!==testedSource} onClick={()=>action(async()=>{
          if(test){const result=await api.builderInstall(test.id);setNotice(`Installed at ${result.path}. Restart the backend and reload Studio to add it to the palette.`);}
        })}>Install tested plugin</button>
        <p>Installation never overwrites a plugin. Restart the backend to discover the new plugin. External dependencies must be installed separately.</p>
      </section>
    </div>
    {error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
  </dialog>;
}
