// SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useRef, useState } from "react";
import { api, type WebotsExample } from "../api/client";
import type { BusMessage } from "../types";
import { KeyboardControl } from "./KeyboardControl";

const descriptions: Record<string, string> = {
  panda: "Robot arm: reach poses and gripper controls in the original factory world.",
  nao: "Humanoid: hand wave and forehead motions, joint telemetry and camera. No walking controller.",
  youbot: "Mobile manipulator: keyboard driving, arm poses and gripper controls. No SLAM or navigation in this example.",
};

export function WebotsExamples({ onClose, onOpen }: { onClose: () => void; onOpen: (id: string) => Promise<void> }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [examples, setExamples] = useState<WebotsExample[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { dialog.current?.showModal(); api.listWebotsExamples().then(setExamples).catch(e => setError(String(e))); }, []);
  return <dialog ref={dialog} onCancel={onClose} aria-label="Webots examples" style={{ maxWidth: 650, padding: 24 }}>
    <h2>Explore existing Webots robots</h2>
    <p>Requires Webots R2025a. Original models, meshes and worlds are reused; the first launch may download assets. Save your current project before replacing it.</p>
    {examples.map(example => <div key={example.id} style={{ marginBottom: 20 }}>
      <strong>{example.title}</strong><p>{descriptions[example.id]}</p>
      <button disabled={busy} onClick={async () => {
        setBusy(true);
        try { await onOpen(example.id); onClose(); } catch (e) { setError(String(e)); } finally { setBusy(false); }
      }}>Open {example.title}</button>
    </div>)}
    {error && <p role="alert">{error}</p>}
    <button disabled={busy} onClick={onClose}>Close</button>
  </dialog>;
}

export function WebotsModelPanel({ nodeId, profile, running, runId, status, teleopId, onUpdate }: {
  nodeId: string; profile: string; running: boolean; runId: string | null; status?: BusMessage; teleopId?: string;
  onUpdate: (id: string, params: Record<string, unknown>) => Promise<void>;
}) {
  const [examples, setExamples] = useState<WebotsExample[]>([]);
  const [viewer, setViewer] = useState<string | null>(null);
  const [manual, setManual] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.listWebotsExamples().then(setExamples).catch(e => setError(String(e)));
    api.getVizUrl().then(v => setViewer(v.available ? v.url : null)).catch(e => setError(String(e)));
  }, []);
  const example = examples.find(e => e.id === profile);
  const current = running && status?.run_id === runId ? status.payload : undefined;
  return <section className="simulation-panel raised" aria-label="Native Webots robot">
    <div className="simulation-controls">
      <strong>{example?.title ?? profile}</strong>
      {example?.actions.map(action => <button key={action} disabled={!running || busy} onClick={async () => {
        if (action === "hold") setManual(false);
        setBusy(true);
        try { await onUpdate(nodeId, { action }); setError(""); } catch (e) { setError(String(e)); } finally { setBusy(false); }
      }}>{action.replaceAll("_", " ")}</button>)}
      {teleopId && <label><input type="checkbox" checked={manual} disabled={!running} onChange={e => setManual(e.target.checked)} /> Manual driving</label>}
    </div>
    <div style={{ padding: "8px 16px" }}>
      <p>3D world: Webots window. Rerun: joint telemetry and available camera. {String(current?.status ?? (running ? "Waiting for Webots…" : "Start Graph to launch Webots."))}</p>
      {Boolean(error || current?.error) && <p role="alert">{error || String(current?.error)}</p>}
      {teleopId && <KeyboardControl nodeId={teleopId} runId={runId} active={running && manual} />}
    </div>
    {viewer ? <iframe title="Webots joint telemetry in Rerun" src={viewer} style={{ width: "100%", minHeight: 260, border: 0 }} /> : <p>Rerun viewer unavailable.</p>}
  </section>;
}
