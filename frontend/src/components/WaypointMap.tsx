import { useEffect, useRef } from "react";
import type { BusMessage } from "../types";

export function WaypointMap({ message, points, path, onAdd, readOnly = false }: {
  readOnly?: boolean; message?: BusMessage; points: number[][]; path?: unknown;
  onAdd: (point: number[]) => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const grid = message?.payload.grid as number[][] | undefined;
  const origin = message?.payload.origin as number[] | undefined;
  const resolution = message?.payload.resolution as number | undefined;
  const pose = message?.payload.pose as number[] | undefined;
  const width = grid?.[0]?.length ?? 1, height = grid?.length ?? 1;
  useEffect(() => {
    if (!grid || !canvas.current) return;
    const context = canvas.current.getContext("2d");
    if (!context) return;
    const image = context.createImageData(width, height);
    for (let row = 0; row < height; row++) for (let col = 0; col < width; col++) {
      const value = grid[row][col];
      const color = value < 0 ? [125, 137, 150] : value >= 50 ? [25, 35, 45] : [235, 242, 247];
      image.data.set([...color, 255], ((height - 1 - row) * width + col) * 4);
    }
    context.putImageData(image, 0, 0);
  }, [grid, width, height]);
  if (!grid || !origin || !resolution) return <p>Waiting for the measured SLAM map…</p>;
  const cell = (point: number[]) => [(point[0] - origin[0]) / resolution, height - (point[1] - origin[1]) / resolution];
  const robot = pose ? cell(pose) : null;
  return <div className="waypoint-map" style={{ aspectRatio: `${width}/${height}` }}>
    <canvas ref={canvas} width={width} height={height} />
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={readOnly ? "Saved occupancy map" : "Click SLAM map to add waypoint"} style={{cursor: readOnly ? "default" : "crosshair"}}
      onClick={(event) => {
        if (readOnly) return;
        const rect = event.currentTarget.getBoundingClientRect();
        const col = Math.min(width - 1, Math.max(0, Math.floor((event.clientX - rect.left) / rect.width * width)));
        const row = Math.min(height - 1, Math.max(0, Math.floor((1 - (event.clientY - rect.top) / rect.height) * height)));
        if (grid[row][col] >= 50) return;
        onAdd([Number((origin[0] + (col + .5) * resolution).toFixed(3)), Number((origin[1] + (row + .5) * resolution).toFixed(3))]);
      }}>
      {Array.isArray(path) && <polyline points={(path as number[][]).map((p) => cell(p).join(",")).join(" ")} fill="none" stroke="#2879e5" strokeWidth=".9" />}
      {points.map((point, index) => { const [x, y] = cell(point); return <g key={index}>
        <circle cx={x} cy={y} r="2" fill="#dd6422" />
        <text x={x + 2} y={y - 2} fontSize="4" fill="#9f3000">{index + 1}</text>
      </g>; })}
      {robot && <path d="M 3 0 L -2 -1.8 L -2 1.8 Z" fill="#09855f" transform={`translate(${robot[0]} ${robot[1]}) rotate(${-pose![2] * 180 / Math.PI})`} />}
    </svg>
  </div>;
}
