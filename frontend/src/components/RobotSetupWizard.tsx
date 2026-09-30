import { useEffect, useRef, useState } from "react";
import { api, type ProjectInfo } from "../api/client";
import type { RobotConfiguration, RobotInspection, RobotPackage, SetupDefaults, SetupDraft, SetupSummary } from "../types/setup";
import { RobotSetupPreview } from "./RobotSetupPreview";
import "../styles/robot-setup.css";

function retainWorld(robot:RobotConfiguration, current:RobotConfiguration):RobotConfiguration {
  if (!current.webots_world) return robot;
  return {...robot,webots_world:current.webots_world,webots_world_hash:current.webots_world_hash,spawn_pose:current.spawn_pose,spawn_height:current.spawn_height,environment:current.environment,mapping:{...current.mapping,inflation_radius:Math.max(current.mapping.inflation_radius,robot.mapping.inflation_radius)}};
}
const STEPS = ["Robot model", "Drive", "Sensors", "Review"];
export function RobotSetupWizard({ projectName, positions, initialModel, onClose, onApplied }: {
  initialModel?:RobotPackage;
  projectName: string; positions: SetupDraft["positions"];
  onClose: () => void; onApplied: (info: ProjectInfo) => Promise<void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [defaults, setDefaults] = useState<SetupDefaults | null>(null);
  const [robot, setRobot] = useState<RobotInspection | null>(null);
  const [draft, setDraft] = useState<SetupDraft | null>(null);
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<SetupSummary | null>(null);
  const [replace, setReplace] = useState(false);

  useEffect(() => {
    dialog.current?.showModal();
    let active = true;
    api.getSetup().then(async initial => {
      if (!active) return;
      setDefaults(initial);
      const source=initialModel??initial;
      if (source.robot_urdf) {
        const inspected = await api.inspectRobot(source.robot_urdf,source.robot_assets);
        if (!active) return;
        setRobot(inspected);
        setDraft({ robot_urdf:source.robot_urdf, robot_assets:source.robot_assets, robot_config:initialModel?retainWorld(inspected.suggested_config,initial.robot_config):initial.robot_config, name:projectName,
          target:initial.node_count ? "configure" : initial.robot_config.webots_world ? "webots" : "builtin", revision:initial.revision, positions });
      }
    }).catch(e => { if (active) setError(String(e)); }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [projectName, positions,initialModel]);

  const inspect = async (xml: string, assets:RobotPackage['robot_assets']={}) => {
    if (!defaults) return;
    setBusy(true); setError(null); setSummary(null);
    try {
      const inspected = await api.inspectRobot(xml,assets);
      setRobot(inspected);
      setDraft({ robot_urdf:xml, robot_assets:assets, robot_config:retainWorld(inspected.suggested_config,defaults.robot_config),
        name:projectName === "Untitled robot" ? inspected.name : projectName,
        target:defaults.node_count ? "configure" : defaults.robot_config.webots_world ? "webots" : "builtin", revision:defaults.revision, positions });
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };
  const update = (values: Partial<SetupDraft>) => { setDraft(d => d ? { ...d,...values } : d); setSummary(null); setError(null); setReplace(false); };
  const drive = draft?.robot_config.drive;
  const setDrive = (values: Partial<RobotConfiguration["drive"]>) => {
    if (draft) update({ robot_config:{ ...draft.robot_config, drive:{ ...draft.robot_config.drive,...values } } });
  };
  const selectFrame = (label: string, key: "base_frame" | "lidar_frame" | "camera_frame") => <label>{label}
    <select aria-label={label} value={drive?.[key] ?? ""} onChange={e => setDrive({ [key]:e.target.value })}>
      <option value="">Choose a frame</option>{robot?.links.map(link => <option key={link.name}>{link.name}</option>)}
    </select></label>;
  const validate = async () => {
    if (!draft) return;
    setBusy(true); setError(null);
    try { setSummary(await api.previewSetup(draft)); }
    catch (e) { setSummary(null); setError(String(e)); }
    finally { setBusy(false); }
  };
  const apply = async () => {
    if (!draft) return;
    setBusy(true); setError(null);
    try { const result = await api.applySetup(draft); await onApplied(result); onClose(); }
    catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };
  const replacing = !!defaults?.node_count && draft?.target !== "configure";
  const canNext = !!robot && !!draft && (step !== 1 || !!drive?.base_frame && [...drive.left_joints,...drive.right_joints].every(Boolean)) &&
    (step !== 2 || !!drive?.lidar_frame && !!drive.camera_frame);

  return <dialog ref={dialog} className="robot-setup" aria-labelledby="setup-title" onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
    <header><div><span className="setup-eyebrow">GUIDED SETUP</span><h2 id="setup-title">Set up your robot</h2><p>From a robot model to a connected simulation.</p></div>
      <button aria-label="Close robot setup" disabled={busy} onClick={onClose}>×</button></header>
    <nav aria-label="Setup progress">{STEPS.map((title,i) => <span key={title} aria-current={step===i ? "step" : undefined} className={step===i ? "current" : ""}>{i+1}. {title}</span>)}</nav>
    <div className="setup-body" aria-busy={busy}>
      <section className="setup-fields">
        {step === 0 && <><h3>Choose your robot model</h3><p>Open a Model Builder ZIP with its meshes, import a URDF, or use the sample robot. Your current project changes only when you apply the setup.</p>
          <div className="setup-actions"><button disabled={busy || !defaults} onClick={() => defaults && inspect(defaults.reference_urdf)}>Use sample robot</button>
            <label className="setup-file">Open Model Builder ZIP<input aria-label="Model Builder ZIP" type="file" accept=".zip" disabled={busy||!defaults} onChange={async e=>{
              const file=e.target.files?.[0];e.target.value='';if(!file)return;
              if(file.size>8*1024*1024){setError('Builder bundle exceeds 8 MiB');return;}
              setBusy(true);setError(null);
              try{const model=await api.importBuilderBundle(file);await inspect(model.robot_urdf,model.robot_assets);}catch(err){setError(String(err));}finally{setBusy(false);}
            }}/></label>
            <label className="setup-file">Choose URDF<input aria-label="Setup URDF file" type="file" accept=".urdf" disabled={busy || !defaults} onChange={async e => {
              const file=e.target.files?.[0]; e.target.value=""; if (!file) return;
              if (file.size>4*1024*1024) { setError("URDF exceeds 4 MiB"); return; }
              try { await inspect(await file.text()); } catch (err) { setError(String(err)); }
            }} /></label></div>
          {robot && <div className="setup-notice"><strong>{robot.name}</strong><p>{robot.links.length} links · {robot.joints.length} joints</p></div>}
          <p>This first setup flow supports four-wheel differential robots with fixed, level lidar and camera mounts. Export Xacro as URDF before importing.</p></>}
        {step === 1 && drive && <><h3>How does your robot move?</h3><p>Four-wheel differential drive: two wheels on each side. Check the suggested assignments against your model.</p>
          {selectFrame("Robot base frame", "base_frame")}
          <div className="setup-two-columns">{(["left", "right"] as const).map(side => <div key={side}>{[0,1].map(index => <label key={index}>{side === "left" ? "Left" : "Right"} {index===0 ? "front" : "rear"} wheel
            <select value={drive[`${side}_joints`][index]} onChange={e => {
              const joints=[...drive[`${side}_joints`]]; joints[index]=e.target.value; setDrive({ [`${side}_joints`]:joints });
            }}><option value="">Choose a joint</option>{robot?.joints.filter(j => ["continuous","revolute"].includes(j.type)).map(j => <option key={j.name}>{j.name}</option>)}</select>
          </label>)}</div>)}</div>
          <label>Wheel radius override (m)<input type="number" min=".001" step=".01" placeholder="Use URDF radius" value={drive.wheel_radius ?? ""}
            onChange={e => setDrive({ wheel_radius:e.target.value==="" ? null : Number(e.target.value) })} /></label>
          <small>For mesh wheels, enter the measured radius. All four wheels must use equal radii and rotate around base +Y. For builder models, place the base frame at ground level and wheel centres one radius above it.</small>
          <div className="setup-two-columns"><label>Robot clearance radius (m)<input type="number" step=".01" min=".01" value={drive.collision_radius} onChange={e => setDrive({collision_radius:Number(e.target.value)})} /></label>
            <label>Encoder ticks per revolution<input type="number" min="1" step="1" value={drive.ticks_per_turn} onChange={e => setDrive({ticks_per_turn:Number(e.target.value)})} /></label></div>
          <label>Planning clearance (m)<input type="number" step=".01" min=".01" value={draft?.robot_config.mapping.inflation_radius}
            onChange={e => draft && update({robot_config:{...draft.robot_config,mapping:{...draft.robot_config.mapping,inflation_radius:Number(e.target.value)}}})} /></label>
          <small>Planning clearance must cover the robot clearance radius. Include your robot's body and wheels.</small>
        </>}
        {step === 2 && <><h3>Where are your sensors?</h3><p>Select the fixed mounting frames. Studio reads their positions and orientations from the URDF.</p>
          {selectFrame("360° lidar frame", "lidar_frame")}{selectFrame("Camera frame", "camera_frame")}
          <div className="setup-notice">Simulation supplies lidar, camera and wheel encoder readings. Physical device connections will be added in a later setup flow.</div>
          <p>Use the camera mounting frame, not an optical frame with a different axis convention.</p>
        </>}
        {step === 3 && draft && <><h3>Review and create</h3>
          <label>Project name<input value={draft.name} maxLength={200} onChange={e => update({name:e.target.value})} /></label>
          <label>Project setup<select aria-label="Project setup" value={draft.target} onChange={e => update({target:e.target.value as SetupDraft["target"]})}>
            <option value="configure">Update robot in current graph</option><option value="builtin">Create built-in simulation project</option><option value="webots">Create Webots simulation project</option>
          </select></label>
          <p>{draft.target === "configure" ? "Keep existing nodes, parameters and connections. Simulator base bindings update to your selection." : "Create a wired graph with simulation, encoders, SLAM, navigation, keyboard driving, drive selection and Rerun. It starts in Stop mode."}</p>
          <button disabled={busy || !draft.name.trim()} onClick={validate}>Check setup</button>
          {summary && <div className="setup-notice setup-success"><strong>Setup checked</strong>
            <p>Wheel radius: {summary.wheel_radius.toFixed(3)} m · Track width: {summary.track.toFixed(3)} m</p>
            <p>{summary.node_count} nodes · {summary.connection_count} connections</p>
            <p>Lidar offset: {(summary.mounts.lidar_link as number[]).slice(0,2).map(v=>v.toFixed(3)).join(", ")} m · height {Number(summary.mounts.lidar_link_height).toFixed(3)} m</p>
            {summary.warnings.map(w => <p key={w}>{w}</p>)}</div>}
          {replacing && <label className="setup-check"><input type="checkbox" checked={replace} onChange={e=>setReplace(e.target.checked)} />Replace the current graph. I have saved any work I want to keep.</label>}
          <p>Applying leaves the graph stopped. Use Start Graph to run, then Save project to keep this configuration.</p>
        </>}
        {busy && <p role="status">Checking robot setup…</p>}
        {error && <div className="setup-error" role="alert">{error}</div>}
      </section>
      <aside>{robot && drive ? <RobotSetupPreview robot={robot} drive={drive} /> : <div className="setup-placeholder">Your robot preview will appear here.</div>}
        {!!robot?.warnings.length && <details><summary>Preview limitations</summary>{robot.warnings.map(w=><p key={w}>{w}</p>)}</details>}</aside>
    </div>
    <footer><button disabled={busy} onClick={onClose}>Cancel</button><div>
      {step>0 && <button disabled={busy} onClick={()=>setStep(value=>Math.max(0,value-1))}>Back</button>}
      {step<3 ? <button className="setup-primary" disabled={busy || !canNext} onClick={()=>{ setStep(value=>Math.min(3,value+1)); setError(null); }}>Next</button>
        : <button className="setup-primary" disabled={busy || !summary || (replacing && !replace)} onClick={apply}>Apply robot setup</button>}
    </div></footer>
  </dialog>;
}
