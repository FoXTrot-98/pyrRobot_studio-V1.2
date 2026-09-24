import { Handle, Position, type NodeProps } from "reactflow";
import type { StudioNodeData } from "../hooks/useGraph";

const CATEGORY_COLORS: Record<string, string> = {
  Sensors: "#3E63DD",
  "Sensors (Examples)": "#3E63DD",
  Processing: "#16A34A",
  Output: "#B7860B",
};

function colorForCategory(category: string): string {
  return CATEGORY_COLORS[category] ?? "#6B7480";
}

export function StudioNode({ data, selected }: NodeProps<StudioNodeData>) {
  const { manifest, params, urdfLink } = data;
  if (!manifest) {
    return (
      <div className="studio-node raised" style={{ color: "var(--danger)", fontSize: 11 }}>
        Unknown plugin
      </div>
    );
  }
  const color = colorForCategory(manifest.category);
  const summaryEntries = Object.entries(params).slice(0, 2);

  return (
    <div className={`studio-node raised${selected ? " selected" : ""}`}>
      <div className="node-head">
        <div className="node-icon raised-sm" style={{ color }}>
          {manifest.icon ?? "◉"}
        </div>
        <div>
          <div className="node-title">{manifest.name}</div>
          <div className="node-sub mono">{data.nodeId}</div>
        </div>
      </div>
      <div className="node-body">
        <div className="node-row" role="status" title={data.error ?? undefined} style={{ color: data.state === "failed" ? "var(--danger)" : undefined }}>
          <span>{data.state ?? "stopped"}</span>
          {data.error && <b>Failed — see inspector</b>}
        </div>
        {summaryEntries.map(([key, value]) => (
          <div className="node-row" key={key}>
            <span>{key}</span>
            <b className="mono">{String(value)}</b>
          </div>
        ))}
        {manifest.requires_urdf_link && (
          <div className="node-row">
            <span>urdf_link</span>
            <b className="mono">{urdfLink ?? "—"}</b>
          </div>
        )}
      </div>

      {manifest.inputs.map((port, i) => (
        <Handle
          key={port.name}
          id={port.name}
          type="target"
          position={Position.Left}
          className="jack"
          title={`${port.name}: ${port.schema ?? port.data_type}${port.required ? " (required)" : " (optional)"}`}
          style={{ top: manifest.inputs.length === 1 ? "50%" : `${((i + 1) / (manifest.inputs.length + 1)) * 100}%` }}
        />
      ))}
      {manifest.outputs.map((port, i) => (
        <Handle
          key={port.name}
          id={port.name}
          type="source"
          position={Position.Right}
          className="jack"
          title={`${port.name}: ${port.schema ?? port.data_type}`}
          style={{ top: manifest.outputs.length === 1 ? "50%" : `${((i + 1) / (manifest.outputs.length + 1)) * 100}%` }}
        />
      ))}
    </div>
  );
}
