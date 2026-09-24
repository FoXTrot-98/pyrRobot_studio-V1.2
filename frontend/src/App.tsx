import { useCallback, useEffect, useMemo, useState } from "react";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlowProvider,
  useReactFlow,
  useNodesInitialized,
  type Node,
} from "reactflow";
import "reactflow/dist/style.css";

import { TopBar } from "./components/TopBar";
import { Palette } from "./components/Palette";
import { Inspector } from "./components/Inspector";
import { GridToolbar, DEFAULT_GRID_SETTINGS, type GridSettings } from "./components/GridToolbar";
import { StudioNode } from "./components/StudioNode";
import { SimulationPanel } from "./components/SimulationPanel";
import { RobotSetupWizard } from "./components/RobotSetupWizard";
import { WebotsExamples, WebotsModelPanel } from "./components/WebotsExamples";
import { useGraph, type StudioNodeData } from "./hooks/useGraph";
import { useBusSocket } from "./hooks/useBusSocket";
import { api, ApiError } from "./api/client";
import type { RobotInfo } from "./types";
import { formatTimecode } from "./utils/prt";

import "./styles/tokens.css";
import "./styles/layout.css";

const nodeTypes = { studioNode: StudioNode };

function gridVariant(style: GridSettings["style"]): BackgroundVariant {
  if (style === "lines") return BackgroundVariant.Lines;
  if (style === "cross") return BackgroundVariant.Cross;
  return BackgroundVariant.Dots;
}

function StudioApp() {
  const { fitView } = useReactFlow();
  const nodesInitialized = useNodesInitialized();
  const graph = useGraph();
  const bus = useBusSocket();

  const [paletteCollapsed, setPaletteCollapsed] = useState(false);
  const [inspectorCollapsed, setInspectorCollapsed] = useState(false);
  const [gridSettings, setGridSettings] = useState<GridSettings>(DEFAULT_GRID_SETTINGS);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [robot, setRobot] = useState<RobotInfo | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [projectName, setProjectName] = useState("Untitled robot");
  const [projectBusy, setProjectBusy] = useState(false);
  const [busyStartStop, setBusyStartStop] = useState(false);
  const [showSimulation, setShowSimulation] = useState(true);
  const [showExamples, setShowExamples] = useState(false);
  const nativeNode = graph.nodes.find(node => node.data.manifest?.id === "pyrobot.sim.webots_model");
  const nativeKeyboard = graph.edges.find(edge => edge.target === nativeNode?.id && edge.targetHandle === "cmd_vel");
  const nativeTeleop = graph.nodes.find(node => node.id === nativeKeyboard?.source && node.data.manifest?.id === "pyrobot.control.keyboard");
  const [setup, setSetup] = useState<{ name: string; positions: Record<string, {x:number;y:number}> } | null>(null);
  const navigationNode = graph.nodes.find((node) => node.data.manifest?.id === "pyrobot.navigation.astar");
  const teleopNode = graph.nodes.find((node) => node.data.manifest?.id === "pyrobot.control.keyboard");
  const selectorNode = graph.nodes.find((node) => node.data.manifest?.id === "pyrobot.control.selector");
  const mapConnection = graph.edges.find((edge) => edge.target === navigationNode?.id && edge.targetHandle === "state");

  useEffect(() => {
    const timer = setTimeout(() => fitView({ padding: .15, duration: 200 }), 150);
    return () => clearTimeout(timer);
  }, [graph.nodes.length, nodesInitialized, showSimulation, fitView]);

  useEffect(() => {
    api.getProject().then((info) => {
      setRobot(info.robot);
      setProjectName(info.name);
    }).catch((e) => setToast(String(e)));
  }, []);

  const saveProject = async () => {
    setProjectBusy(true);
    try {
      const positions = Object.fromEntries(graph.nodes.map((n) => [n.id, n.position]));
      const document = await api.exportProject(projectName.trim(), positions);
      const url = URL.createObjectURL(new Blob([JSON.stringify(document, null, 2)], { type: "application/json" }));
      const anchor = window.document.createElement("a");
      anchor.href = url;
      anchor.download = `${projectName.replace(/[^a-z0-9_-]/gi, "_") || "robot"}.pyrobot.json`;
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      setToast(e instanceof Error ? e.message : String(e));
    } finally {
      setProjectBusy(false);
    }
  };

  const openProject = async (file: File) => {
    if (graph.nodes.length && !window.confirm("Opening this project replaces the current graph. Save your current project first if you want to keep it. Continue?")) return;
    setProjectBusy(true);
    try {
      if (file.size > 8 * 1024 * 1024) throw new Error("Project exceeds 8 MiB");
      const info = await api.importProject(JSON.parse(await file.text()));
      setProjectName(info.name);
      setRobot(info.robot);
      setSelectedNodeId(null);
      graph.dismissError();
      setToast(null);
      await graph.refreshFromBackend(info.positions);
    } catch (e) {
      setToast(e instanceof Error ? e.message : String(e));
    } finally {
      setProjectBusy(false);
    }
  };

  const selectedNode: Node<StudioNodeData> | null = useMemo(
    () => graph.nodes.find((n) => n.id === selectedNodeId) ?? null,
    [graph.nodes, selectedNodeId]
  );

  const liveMessageForSelected = useMemo(() => {
    if (!selectedNode?.data.manifest) return undefined;
    // a node's live output shows on its first declared output port's topic
    const firstOutput = selectedNode.data.manifest.outputs[0];
    if (!firstOutput) return undefined;
    return bus.getLatestForTopic(`node/${selectedNode.id}/out/${firstOutput.name}`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedNode, bus.byTopicVersion]);

  const handleUploadUrdf = useCallback(async (file: File) => {
    try {
      const info = await api.uploadUrdf(file);
      setRobot(info);
    } catch (e) {
      setToast(e instanceof ApiError ? `URDF upload failed: ${e.message}` : String(e));
    }
  }, []);

  const handleToggleRunning = useCallback(async () => {
    setBusyStartStop(true);
    try {
      await graph.toggleRunning();
    } finally {
      setBusyStartStop(false);
    }
  }, [graph]);

  const handleAddNode = useCallback(
    (pluginId: string) => {
      const manifest = graph.plugins.find((p) => p.id === pluginId);
      if (manifest?.requires_urdf_link && !robot) {
        setToast(`${manifest.name} requires a URDF link — upload a robot URDF first.`);
        return;
      }
      const urdfLink = manifest?.requires_urdf_link ? robot?.links[0] : undefined;
      graph.addNodeToGraph(pluginId, urdfLink);
    },
    [graph, robot]
  );

  const error = graph.error ?? toast;

  return (
    <div className="app-shell">
      <TopBar
        robot={robot}
        onUploadUrdf={handleUploadUrdf}
        connected={bus.connected}
        timecode={bus.latest ? formatTimecode((bus.latest.published_ts ?? bus.latest.ts).epoch_ns) : "00:00:00:00"}
        running={graph.running}
        onToggleRunning={handleToggleRunning}
        busy={busyStartStop || projectBusy}
        projectName={projectName}
        onProjectName={setProjectName}
        onSaveProject={saveProject}
        onOpenProject={openProject}
        onRobotSetup={() => setSetup({name:projectName,positions:Object.fromEntries(graph.nodes.map(n=>[n.id,n.position]))})}
        onExamples={() => setShowExamples(true)}
      />
      {showExamples && <WebotsExamples onClose={() => setShowExamples(false)} onOpen={async id => {
        if (graph.nodes.length && !window.confirm("Replace the current graph with this example? Save your project first to keep it.")) return;
        setProjectBusy(true);
        try {
          const info = await api.importProject(await api.getWebotsExample(id));
          setProjectName(info.name); setRobot(info.robot); setSelectedNodeId(null); graph.dismissError(); setToast(null);
          await graph.refreshFromBackend(info.positions);
        } finally { setProjectBusy(false); }
      }} />}
      {setup && <RobotSetupWizard projectName={setup.name} positions={setup.positions} onClose={()=>setSetup(null)}
        onApplied={async info => {
          setProjectName(info.name); setRobot(info.robot); setSelectedNodeId(null); graph.dismissError();
          setToast("Robot setup applied. Start Graph to run; Save project to keep your changes.");
          await graph.refreshFromBackend(info.positions);
        }} />}

      <div className="content" inert={projectBusy}>
        <Palette
          plugins={graph.plugins}
          collapsed={paletteCollapsed}
          onToggleCollapse={() => setPaletteCollapsed((c) => !c)}
          onAddNode={handleAddNode}
        />

        <div className="workspace-center">
        <div className="canvas-wrap raised">
          <ReactFlow
            nodes={graph.nodes}
            edges={graph.edges}
            nodeTypes={nodeTypes}
            onNodesChange={graph.onNodesChange}
            onConnect={graph.onConnect}
            deleteKeyCode={null}
            onEdgeDoubleClick={(_, edge) => graph.removeConnection(edge)}
            onNodeClick={(_, node) => setSelectedNodeId(node.id)}
            onPaneClick={() => setSelectedNodeId(null)}
            snapToGrid={gridSettings.visible && gridSettings.snap}
            snapGrid={[gridSettings.spacing, gridSettings.spacing]}
            fitView
            minZoom={0.15}
            proOptions={{ hideAttribution: true }}
          >
            {gridSettings.visible && (
              <Background
                variant={gridVariant(gridSettings.style)}
                gap={gridSettings.spacing}
                size={gridSettings.style === "dots" ? 1.4 : 1}
                color={`rgba(107,116,128,${gridSettings.opacity})`}
              />
            )}
            <Controls showInteractive={false} />
          </ReactFlow>

          <div className="canvas-toolbar raised-sm" style={{ position: "absolute", top: 16, left: 16 }}>
            <GridToolbar settings={gridSettings} onChange={setGridSettings} />
            <span className="canvas-hint">Double-click a wire to disconnect</span>
            {navigationNode && <button className="simulation-toggle" onClick={() => setShowSimulation((value) => !value)}>{showSimulation ? "Hide 3D" : "Show 3D"}</button>}
          </div>

          {error && (
            <div className="error-toast raised">
              <span>{error}</span>
              <button onClick={() => (graph.error ? graph.dismissError() : setToast(null))}>✕</button>
            </div>
          )}
        </div>
        {navigationNode && showSimulation && <SimulationPanel
          key={navigationNode.id}
          nodeId={navigationNode.id}
          params={navigationNode.data.params}
          running={graph.running}
          runId={graph.runId}
          status={bus.getLatestForTopic(`node/${navigationNode.id}/out/path`)}
          map={mapConnection ? bus.getLatestForTopic(`node/${mapConnection.source}/out/${mapConnection.sourceHandle}`) : undefined}
          teleopId={teleopNode?.id}
          selector={selectorNode ? { id: selectorNode.id, mode: String(selectorNode.data.params.mode) } : undefined}
          onUpdate={graph.updateNodeParams}
        />}
        {nativeNode && <WebotsModelPanel key={`${nativeNode.id}:${graph.runId}:${String(nativeNode.data.params.profile)}`}
          nodeId={nativeNode.id} profile={String(nativeNode.data.params.profile)} running={graph.running} runId={graph.runId}
          status={bus.getLatestForTopic(`node/${nativeNode.id}/out/state`)} teleopId={nativeTeleop?.id} onUpdate={graph.updateNodeParams} />}
        </div>

        <Inspector
          key={selectedNodeId ?? "none"}
          selectedNode={selectedNode}
          robotLinks={robot?.links ?? []}
          running={graph.running}
          onUpdateBinding={graph.updateBinding}
          collapsed={inspectorCollapsed}
          onToggleCollapse={() => setInspectorCollapsed((c) => !c)}
          onRemove={(nodeId) => {
            graph.removeNodeFromGraph(nodeId);
            setSelectedNodeId(null);
          }}
          onUpdateParam={graph.updateNodeParam}
          liveMessage={liveMessageForSelected}
        />
      </div>
    </div>
  );
}

export default function App() {
  return (
    <ReactFlowProvider>
      <StudioApp />
    </ReactFlowProvider>
  );
}
