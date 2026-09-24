import { useEffect, useRef, useState } from "react";

interface RemoteStatus {
  protocol: number; hostname: string; os: string; architecture: string; python: string;
  project: string; revision: string | null;
  graph: { running: boolean; failure_reason?: string; nodes: { node_id: string; state: string; error: string | null }[] };
}
interface Check { compatible: boolean; diagnostics: { message: string }[]; note?: string }

export function DeploymentPanel({ onClose, exportProject }: { onClose: () => void; exportProject: () => Promise<unknown> }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [address, setAddress] = useState("http://127.0.0.1:8765");
  const [token, setToken] = useState("");
  const [session, setSession] = useState<{ address: string; token: string } | null>(null);
  const [status, setStatus] = useState<RemoteStatus | null>(null);
  const [checked, setChecked] = useState<{ document: unknown; result: Check } | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [replace, setReplace] = useState(false);
  useEffect(() => { dialog.current?.showModal(); }, []);

  async function request<T>(connection: { address: string; token: string }, path: string, body?: unknown): Promise<T> {
    const url = new URL(connection.address);
    if (url.username || url.password || url.search || url.hash || !["http:", "https:"].includes(url.protocol)) throw new Error("Enter an HTTP(S) agent address without credentials or query parameters.");
    if (url.protocol === "http:" && !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)) throw new Error("Use HTTPS for a remote robot, or connect through a localhost SSH tunnel.");
    const response = await fetch(connection.address.replace(/\/$/, "") + path, {
      method: body === undefined ? "GET" : "POST", headers: { Authorization: `Bearer ${connection.token}`, "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(30000), redirect: "error",
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
    return data as T;
  }
  async function act(operation: () => Promise<void>) {
    setBusy(true); setError("");
    try { await operation(); } catch (e) { setError(`${String(e)}. If a command timed out, refresh status before retrying.`); }
    finally { setBusy(false); }
  }
  async function refresh() {
    if (!session) return;
    setStatus(await request<RemoteStatus>(session, "/agent/status"));
    setLogs((await request<{ lines: string[] }>(session, "/agent/logs")).lines);
  }
  return <dialog ref={dialog} onCancel={event => { if (busy) event.preventDefault(); else onClose(); }} aria-label="Robot connection and deployment"
    style={{ width: "min(850px, 90vw)", maxHeight: "90vh", overflow: "auto", padding: 24 }}>
    <h2>Robot connection and deployment</h2>
    <p>Run the PyRobot agent on your robot computer, then enter its address and token. Connect by address in this version; automatic discovery is not yet available.</p>
    <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
      <label>Agent address <input aria-label="Agent address" value={address} disabled={busy || !!session} onChange={e => setAddress(e.target.value)} /></label>
      <label>Agent token <input aria-label="Agent token" type="password" autoComplete="off" value={token} disabled={busy || !!session} onChange={e => setToken(e.target.value)} /></label>
      <button disabled={busy || !token || !!session} onClick={() => act(async () => {
        const connection = { address: address.trim(), token };
        const remote = await request<RemoteStatus>(connection, "/agent/status");
        if (remote.protocol !== 1) throw new Error("Unsupported agent protocol");
        setStatus(remote); setSession(connection); setChecked(null); setLogs([]); setReplace(false);
      })}>Connect</button>
      {session && <button disabled={busy} onClick={() => { setSession(null); setStatus(null); setChecked(null); setLogs([]); setToken(""); }}>Disconnect</button>}
    </div>
    {status && session && <>
      <p><strong>{status.hostname}</strong> · {status.os} {status.architecture} · Python {status.python}</p>
      <p>Remote project: <strong>{status.project}</strong> · {status.graph.running ? "Running" : "Stopped"} · revision {status.revision?.slice(0, 12) ?? "none deployed"}</p>
      <button disabled={busy} onClick={() => act(refresh)}>Refresh status and logs</button>
      <hr />
      <p>Check takes a snapshot of your current Studio project. Transfer sends that checked snapshot, including its URDF and configuration. Plugins, model weights and external files must already exist on the robot.</p>
      <button disabled={busy} onClick={() => act(async () => {
        setChecked(null); setReplace(false);
        const document = await exportProject();
        const result = await request<Check>(session, "/agent/check", document);
        setChecked({ document, result });
      })}>Check current project</button>
      {checked && <div role="status">
        <p>{checked.result.compatible ? "Compatibility checks passed" : "Project is not compatible"}</p>
        {checked.result.diagnostics.map((d, i) => <p key={i}>{d.message}</p>)}
        <p>{checked.result.note}</p>
      </div>}
      <p><label><input type="checkbox" checked={replace} onChange={e => setReplace(e.target.checked)} disabled={busy} /> Replace the stopped remote project with this snapshot</label></p>
      <button disabled={busy || !checked?.result.compatible || !replace || status.graph.running} onClick={() => act(async () => {
        setStatus(await request<RemoteStatus>(session, "/agent/deploy", checked!.document)); setChecked(null); setReplace(false);
      })}>Transfer project</button>
      <button disabled={busy || status.graph.running || !status.revision} onClick={() => act(async () => {
        setStatus(await request<RemoteStatus>(session, "/agent/start", { revision: status.revision }));
      })}>Start remote</button>
      <button disabled={busy} onClick={() => act(async () => { setStatus(await request<RemoteStatus>(session, "/agent/stop", {})); })}>Stop remote</button>
      {status.graph.failure_reason && <p role="alert">{status.graph.failure_reason}</p>}
      <ul>{status.graph.nodes.map(node => <li key={node.node_id}>{node.node_id}: {node.state} {node.error}</li>)}</ul>
      <h3>Recent agent logs</h3>
      <pre style={{ maxHeight: 220, overflow: "auto", whiteSpace: "pre-wrap" }}>{logs.join("\n") || "Refresh status and logs to read recent output."}</pre>
    </>}
    {error && <p role="alert">{error}</p>}
    <p>Closing or disconnecting this screen leaves the remote graph running. Use Stop remote before disconnecting when you want it stopped.</p>
    <p>Firmware flashing is separate and is not supported by this screen yet.</p>
    <button disabled={busy} onClick={onClose}>Close</button>
  </dialog>;
}
