import { useRef } from "react";
import type { RobotInfo } from "../types";

interface Props {
  robot: RobotInfo | null;
  onUploadUrdf: (file: File) => void;
  connected: boolean;
  timecode: string;
  running: boolean;
  onToggleRunning: () => void;
  busy: boolean;
  projectName: string;
  onProjectName: (name: string) => void;
  onSaveProject: () => void;
  onOpenProject: (file: File) => void;
  onRobotSetup: () => void;
  onExamples: () => void;
  onDeploy: () => void;
  onPluginBuilder: () => void;
  onModelBuilder: () => void;
}

export function TopBar({ robot, onUploadUrdf, connected, timecode, running, onToggleRunning, busy, projectName, onProjectName, onSaveProject, onOpenProject, onRobotSetup, onExamples, onDeploy, onPluginBuilder, onModelBuilder }: Props) {
  const projectInputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  return (
    <div className="topbar raised">
      <div className="brand">
        <div className="brand-mark raised-sm">◈</div>
        <div>
          <div className="brand-name">PyRobot Studio</div>
          <div className="brand-sub mono">v4.0.0-dev</div>
        </div>
      </div>

      <button className="robot-select raised-sm" disabled={busy || running} onClick={onRobotSetup}>Robot setup</button>
      <button className="robot-select raised-sm" disabled={busy || running} onClick={onExamples}>Examples</button>
      <button className="robot-select raised-sm" disabled={busy} onClick={onDeploy}>Deploy</button>
      <button className="robot-select raised-sm" disabled={busy||running} onClick={onPluginBuilder}>Plugin Builder</button>
      <button className="robot-select raised-sm" disabled={busy||running} onClick={onModelBuilder}>Model Builder</button>
      <button className="robot-select raised-sm" disabled={busy || running} onClick={() => fileInputRef.current?.click()}>
        <span>Robot:</span> <b>{robot?.name ?? "no URDF loaded"}</b>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>
      <input
        ref={fileInputRef}
        type="file"
        accept=".urdf,.xacro"
        style={{ display: "none" }}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onUploadUrdf(file);
          e.target.value = "";
        }}
      />

      <div className="project-controls">
        <input className="project-name inset" aria-label="Project name" maxLength={200}
          value={projectName} onChange={(e) => onProjectName(e.target.value)} />
        <button className="robot-select raised-sm" disabled={busy || !projectName.trim()} onClick={onSaveProject}>Save project</button>
        <button className="robot-select raised-sm" disabled={busy || running}
          title={running ? "Stop the graph before opening a project" : "Open a saved project"}
          onClick={() => projectInputRef.current?.click()}>Open project</button>
        <input ref={projectInputRef} type="file" accept=".json,.pyrobot" hidden onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onOpenProject(file);
          e.target.value = "";
        }} />
      </div>
      <div className="topbar-right">
        <div className="timecode inset mono">
          <span className={`live-dot${connected ? "" : " offline"}`} />
          {timecode}
          <span className="rate">{connected ? "bus·connected" : "bus·offline"}</span>
        </div>
        <button className={`run-btn${running ? " stop" : ""}`} onClick={onToggleRunning} disabled={busy}>
          {running ? (
            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
              <rect x="6" y="6" width="12" height="12" />
            </svg>
          ) : (
            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
              <polygon points="6,4 20,12 6,20" />
            </svg>
          )}
          {running ? "Stop Graph" : "Start Graph"}
        </button>
      </div>
    </div>
  );
}
