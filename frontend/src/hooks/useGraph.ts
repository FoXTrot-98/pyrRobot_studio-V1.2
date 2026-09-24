import { useCallback, useEffect, useState } from "react";
import { addEdge, applyNodeChanges, type Connection, type Edge, type Node, type NodeChange } from "reactflow";
import { api, ApiError } from "../api/client";
import type { GraphNode, PluginManifest } from "../types";

export interface StudioNodeData {
  nodeId: string;
  manifest: PluginManifest;
  params: Record<string, unknown>;
  urdfLink: string | null;
  state?: string;
  error?: string | null;
}

/** Local storage key for remembering canvas layout between sessions —
 * the backend intentionally doesn't track visual position, only graph topology. */
const LAYOUT_KEY = "pyrobot-studio.node-positions";

function loadSavedPositions(): Record<string, { x: number; y: number }> {
  try {
    return JSON.parse(localStorage.getItem(LAYOUT_KEY) || "{}");
  } catch {
    return {};
  }
}

function savePosition(nodeId: string, position: { x: number; y: number }) {
  const all = loadSavedPositions();
  all[nodeId] = position;
  localStorage.setItem(LAYOUT_KEY, JSON.stringify(all));
}

let autoLayoutCounter = 0;
function nextAutoPosition(): { x: number; y: number } {
  const col = autoLayoutCounter % 4;
  const row = Math.floor(autoLayoutCounter / 4);
  autoLayoutCounter += 1;
  return { x: 60 + col * 240, y: 80 + row * 190 };
}

export function useGraph() {
  const [plugins, setPlugins] = useState<PluginManifest[]>([]);
  const [nodes, setNodes] = useState<Node<StudioNodeData>[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [running, setRunning] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const pluginById = useCallback(
    (id: string) => plugins.find((p) => p.id === id),
    [plugins]
  );

  const refreshFromBackend = useCallback(async (positions?: Record<string, { x: number; y: number }>) => {
    const [pluginRes, graphRes] = await Promise.all([api.listPlugins(), api.getGraph()]);
    setPlugins(pluginRes.plugins);
    setRunning(graphRes.running);
    setRunId(graphRes.run_id ?? null);

    const saved = positions ?? loadSavedPositions();
    if (positions) localStorage.setItem(LAYOUT_KEY, JSON.stringify(positions));
    const rfNodes: Node<StudioNodeData>[] = graphRes.nodes.map((n: GraphNode) => {
      const manifest = pluginRes.plugins.find((p) => p.id === n.plugin_id);
      const position = saved[n.node_id] || nextAutoPosition();
      return {
        id: n.node_id,
        type: "studioNode",
        position,
        data: {
          nodeId: n.node_id,
          manifest: manifest as PluginManifest,
          params: n.params,
          urdfLink: n.urdf_link,
          state: n.state,
          error: n.error,
        },
      };
    });

    const rfEdges: Edge[] = graphRes.connections.map((c) => ({
      id: `${c.from_node}.${c.from_port}->${c.to_node}.${c.to_port}`,
      source: c.from_node,
      sourceHandle: c.from_port,
      target: c.to_node,
      targetHandle: c.to_port,
      animated: graphRes.running,
    }));

    setNodes(rfNodes);
    setEdges(rfEdges);
  }, []);

  useEffect(() => {
    setLoading(true);
    refreshFromBackend()
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [refreshFromBackend]);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const snapshot = await api.getGraph();
        if (cancelled) return;
        setRunning(snapshot.running);
        setRunId(snapshot.run_id ?? null);
        if (snapshot.failure_reason) setError(`Graph stopped: ${snapshot.failure_reason}`);
        const health = new Map(snapshot.nodes.map((node) => [node.node_id, node]));
        setNodes((nodes) => {
          let changed = false;
          const next = nodes.map((node) => {
          const current = health.get(node.id);
          if (!current || (node.data.state === current.state && node.data.error === current.error)) return node;
          changed = true;
          return { ...node, data: { ...node.data, state: current.state, error: current.error } };
          });
          return changed ? next : nodes;
        });
        setEdges((edges) => edges.some((edge) => edge.animated !== snapshot.running)
          ? edges.map((edge) => ({ ...edge, animated: snapshot.running })) : edges);
      } catch { /* The connection indicator handles backend availability. */ }
      finally { if (!cancelled) timer = setTimeout(poll, 500); }
    };
    timer = setTimeout(poll, 500);
    return () => { cancelled = true; clearTimeout(timer); };
  }, []);

  const onNodesChange = useCallback((changes: NodeChange[]) => {
    setNodes((nds) => {
      const next = applyNodeChanges(changes, nds);
      // persist position changes as they happen (drag end is a "position" change with dragging:false)
      for (const change of changes) {
        if (change.type === "position" && change.position && change.dragging === false) {
          savePosition(change.id, change.position);
        }
      }
      return next;
    });
  }, []);

  const addNodeToGraph = useCallback(
    async (pluginId: string, urdfLink?: string | null) => {
      const manifest = pluginById(pluginId);
      if (!manifest) return;
      const nodeId = `${pluginId.split(".").pop()}-${Math.random().toString(36).slice(2, 6)}`;
      const params: Record<string, unknown> = {};
      for (const p of manifest.params) params[p.name] = p.default;

      try {
        await api.addNode(nodeId, pluginId, params, urdfLink);
        const position = nextAutoPosition();
        savePosition(nodeId, position);
        setNodes((nds) => [
          ...nds,
          { id: nodeId, type: "studioNode", position, data: { nodeId, manifest, params, urdfLink: urdfLink ?? null } },
        ]);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : String(e));
      }
    },
    [pluginById]
  );

  const removeNodeFromGraph = useCallback(async (nodeId: string) => {
    try {
      await api.removeNode(nodeId);
      setNodes((nds) => nds.filter((n) => n.id !== nodeId));
      setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, []);

  const updateNodeParam = useCallback(async (nodeId: string, key: string, value: unknown) => {
    try {
      await api.updateNodeParams(nodeId, { [key]: value });
      setNodes((nds) =>
        nds.map((n) =>
          n.id === nodeId ? { ...n, data: { ...n.data, params: { ...n.data.params, [key]: value } } } : n
        )
      );
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, []);

  const updateNodeParams = useCallback(async (nodeId: string, updates: Record<string, unknown>) => {
    await api.updateNodeParams(nodeId, updates);
    setNodes((nds) => nds.map((n) => n.id === nodeId
      ? { ...n, data: { ...n.data, params: { ...n.data.params, ...updates } } } : n));
  }, []);

  const onConnect = useCallback(async (connection: Connection) => {
    if (!connection.source || !connection.target || !connection.sourceHandle || !connection.targetHandle) return;
    try {
      await api.connect(connection.source, connection.sourceHandle, connection.target, connection.targetHandle);
      setEdges((eds) => addEdge({ ...connection, id: `${connection.source}.${connection.sourceHandle}->${connection.target}.${connection.targetHandle}` }, eds));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, []);

  const removeConnection = useCallback(async (edge: Edge) => {
    if (!edge.sourceHandle || !edge.targetHandle) return;
    try {
      await api.disconnect(edge.source, edge.sourceHandle, edge.target, edge.targetHandle);
      setEdges((eds) => eds.filter((e) => e.id !== edge.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const updateBinding = useCallback(async (nodeId: string, link: string) => {
    try {
      await api.updateBinding(nodeId, link);
      setNodes((nds) => nds.map((n) => n.id === nodeId ? { ...n, data: { ...n.data, urdfLink: link } } : n));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const toggleRunning = useCallback(async () => {
    try {
      const result = running ? await api.stopGraph() : await api.startGraph();
      setRunning(result.running);
      setRunId(result.run_id ?? null);
      setEdges((eds) => eds.map((e) => ({ ...e, animated: result.running })));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, [running]);

  return {
    plugins,
    nodes,
    edges,
    running,
    runId,
    loading,
    error,
    dismissError: () => setError(null),
    onNodesChange,
    onConnect,
    addNodeToGraph,
    removeNodeFromGraph,
    updateNodeParam,
    updateNodeParams,
    toggleRunning,
    refreshFromBackend,
    removeConnection,
    updateBinding,
  };
}
