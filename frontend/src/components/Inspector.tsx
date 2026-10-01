// SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
// SPDX-License-Identifier: Apache-2.0

import type { Node } from "reactflow";
import type { StudioNodeData } from "../hooks/useGraph";
import type { BusMessage } from "../types";

interface Props {
  selectedNode: Node<StudioNodeData> | null;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onRemove: (nodeId: string) => void;
  onUpdateParam: (nodeId: string, key: string, value: unknown) => void;
  liveMessage: BusMessage | undefined;
  robotLinks: string[];
  running: boolean;
  onUpdateBinding: (nodeId: string, link: string) => void;
}

export function Inspector({ selectedNode, collapsed, onToggleCollapse, onRemove, onUpdateParam, liveMessage, robotLinks, running, onUpdateBinding }: Props) {
  const data = selectedNode?.data;
  const manifest = data?.manifest;

  return (
    <div className={`side-panel right raised${collapsed ? " collapsed" : ""}`}>
      <div className="panel-head">
        <span className="panel-label">INSPECTOR</span>
        <button className="collapse-btn raised-sm" onClick={onToggleCollapse} title="Collapse">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M15 6l-6 6 6 6" />
          </svg>
        </button>
      </div>
      <div className="panel-body">
        <div className="panel-body-inner full">
          {!manifest && (
            <div className="insp-empty">Select a node on the canvas to see its details here.</div>
          )}

          {manifest && data && (
            <>
              <div className="insp-head">
                <div className="insp-icon raised-sm">{manifest.icon ?? "◉"}</div>
                <div>
                  <div className="insp-title">{manifest.name}</div>
                  <div className="insp-plugin mono">{manifest.id}</div>
                </div>
              </div>
              <div className="insp-desc">{manifest.description || "No description provided."}</div>
              <div role="status">State: {data.state ?? "stopped"}</div>
              {data.error && <div role="alert" style={{ color: "var(--danger)", overflowWrap: "anywhere" }}>{data.error}</div>}

              <div className="field-label">NODE ID</div>
              <div className="field inset">
                <span className="mono">{data.nodeId}</span>
              </div>

              {manifest.inputs.length > 0 && (
                <>
                  <div className="field-label">INPUT PORTS</div>
                  {manifest.inputs.map((p) => (
                    <div className="field inset" key={p.name} style={{ marginBottom: 8 }}>
                      <span>{p.name}</span>
                      <span className="mono" style={{ color: "var(--text-tertiary)" }}>
                        {p.schema ?? p.data_type}{p.required ? " · required" : " · optional"}
                      </span>
                    </div>
                  ))}
                </>
              )}

              {manifest.outputs.length > 0 && (
                <>
                  <div className="field-label">OUTPUT PORTS</div>
                  {manifest.outputs.map((p) => (
                    <div className="field inset" key={p.name} style={{ marginBottom: 8 }}>
                      <span>{p.name}</span>
                      <span className="mono" style={{ color: "var(--text-tertiary)" }}>
                        {p.schema ?? p.data_type}
                      </span>
                    </div>
                  ))}
                </>
              )}

              {manifest.params.length > 0 && (
                <>
                  <div className="field-label">PARAMETERS</div>
                  {manifest.params.map((p) => {
                    const value = data.params[p.name] ?? p.default;
                    return (
                      <div className="field inset" key={p.name} style={{ marginBottom: 8 }} title={p.description}>
                        <span>{p.name}</span>
                        {p.kind === "number" && (
                          <input
                            className="mono param-input"
                            type="number"
                            min={p.min ?? undefined}
                            max={p.max ?? undefined}
                            defaultValue={String(value)}
                            onBlur={(e) => {
                              const n = Number(e.target.value);
                              if (!Number.isNaN(n) && n !== value) onUpdateParam(data.nodeId, p.name, n);
                            }}
                          />
                        )}
                        {p.kind === "json" && <textarea className="mono param-input" defaultValue={JSON.stringify(value)}
                          onBlur={(e) => {
                            try { onUpdateParam(data.nodeId, p.name, JSON.parse(e.target.value)); e.target.setCustomValidity(""); }
                            catch { e.target.setCustomValidity("Enter valid JSON"); e.target.reportValidity(); }
                          }} />}
                        {p.kind === "bool" && (
                          <input
                            type="checkbox"
                            checked={Boolean(value)}
                            onChange={(e) => onUpdateParam(data.nodeId, p.name, e.target.checked)}
                          />
                        )}
                        {p.kind === "enum" && (
                          <select
                            className="mono param-input"
                            value={String(value)}
                            onChange={(e) => onUpdateParam(data.nodeId, p.name, e.target.value)}
                          >
                            {(p.options ?? []).map((opt) => (
                              <option key={opt} value={opt}>
                                {opt}
                              </option>
                            ))}
                          </select>
                        )}
                        {(p.kind === "string" || p.kind === "file") && (
                          <input
                            className="mono param-input"
                            type="text"
                            defaultValue={String(value)}
                            onBlur={(e) => {
                              if (e.target.value !== value) onUpdateParam(data.nodeId, p.name, e.target.value);
                            }}
                          />
                        )}
                      </div>
                    );
                  })}
                </>
              )}

              <div className="field-label">URDF BINDING</div>
              <div className="field inset">
                {manifest.requires_urdf_link ? (
                  <select aria-label="Robot link" className="param-input" value={data.urdfLink ?? ""}
                    disabled={running} title={running ? "Stop the graph to change its robot binding" : "Sensor mount link"}
                    onChange={(e) => onUpdateBinding(data.nodeId, e.target.value)}>
                    {robotLinks.map((link) => <option key={link} value={link}>{link}</option>)}
                  </select>
                ) : <span>not required</span>}
              </div>

              {liveMessage && (
                <>
                  <div className="field-label">LIVE VALUE — {liveMessage.topic}</div>
                  <div
                    className="field inset-deep mono"
                    style={{ fontSize: 10.5, lineHeight: 1.6, display: "block", whiteSpace: "pre-wrap" }}
                  >
                    {JSON.stringify(liveMessage.payload, null, 2)}
                  </div>
                </>
              )}

              <button className="insp-remove-btn" onClick={() => onRemove(data.nodeId)}>
                Remove Node
              </button>
            </>
          )}
        </div>
        <div className="collapsed-rail">
          {manifest && <div className="rail-icon raised-sm">{manifest.icon ?? "◉"}</div>}
        </div>
      </div>
    </div>
  );
}
