import { useState } from "react";
import type { RobotInspection, RobotConfiguration } from "../types/setup";

export function RobotSetupPreview({ robot, drive }: { robot: RobotInspection; drive: RobotConfiguration["drive"] }) {
  const [angle, setAngle] = useState(35);
  const yaw = angle*Math.PI/180;
  const project = (p: number[]) => [
    p[0]*Math.cos(yaw)-p[1]*Math.sin(yaw),
    .45*(p[0]*Math.sin(yaw)+p[1]*Math.cos(yaw))-p[2],
    p[0]*Math.sin(yaw)+p[1]*Math.cos(yaw)+.45*p[2],
  ];
  const projected = robot.links.flatMap((link) => [...link.vertices, link.xyz]).map(project);
  const minX = Math.min(...projected.map(p => p[0])), maxX = Math.max(...projected.map(p => p[0]));
  const minY = Math.min(...projected.map(p => p[1])), maxY = Math.max(...projected.map(p => p[1]));
  const scale = Math.min(300/Math.max(.1,maxX-minX),230/Math.max(.1,maxY-minY));
  const screen = (p: number[]) => { const v = project(p); return [200+(v[0]-(minX+maxX)/2)*scale,165+(v[1]-(minY+maxY)/2)*scale,v[2]]; };
  const wheelLinks = robot.joints.filter(j => [...drive.left_joints,...drive.right_joints].includes(j.name)).map(j => j.child);
  const color = (name: string) => name === drive.lidar_frame ? "#0e9578" : name === drive.camera_frame ? "#dd8125" : wheelLinks.includes(name) ? "#33445d" : "#7596c5";
  const faces = robot.links.flatMap(link => link.faces.map(face => {
    const points = face.map(i => screen(link.vertices[i]));
    return { name:link.name, points, depth:points.reduce((sum,p) => sum+p[2],0)/points.length };
  })).sort((a,b) => a.depth-b.depth);
  return <div className="setup-preview">
    <svg viewBox="0 0 400 330" role="img" aria-label="Robot URDF preview">
      <defs><pattern id="setup-grid" width="24" height="24" patternUnits="userSpaceOnUse"><path d="M 24 0 L 0 0 0 24" fill="none" stroke="#ced8e6" strokeWidth=".7" /></pattern></defs>
      <rect width="400" height="330" fill="url(#setup-grid)" rx="16" />
      {faces.map((face,i) => <polygon key={i} points={face.points.map(p => p.slice(0,2).join(",")).join(" ")}
        fill={color(face.name)} stroke="#edf3fa" strokeWidth=".6" fillOpacity=".9"><title>{face.name}</title></polygon>)}
      {robot.links.filter(link => !link.vertices.length || [drive.base_frame,drive.lidar_frame,drive.camera_frame].includes(link.name)).map(link => {
        const [x,y] = screen(link.xyz);
        const selected = [drive.base_frame,drive.lidar_frame,drive.camera_frame].includes(link.name);
        return <g key={link.name}><title>{link.name}</title><circle cx={x} cy={y} r={selected ? 4 : 2} fill={color(link.name)} stroke="white" />
          {selected && <text x={x>200 ? x-7 : x+7} textAnchor={x>200 ? "end" : "start"} y={y-7} fontSize="11" fill="#203047" stroke="#f5f8fc" strokeWidth="3" paintOrder="stroke">{link.name}</text>}</g>;
      })}
    </svg>
    <label>View angle <input aria-label="Preview view angle" type="range" min="-180" max="180" value={angle} onChange={e => setAngle(Number(e.target.value))} /></label>
    <p>URDF at zero joint positions · dimensions in metres</p>
    <div className="setup-legend"><span>● Wheels</span><span style={{color:"#0e9578"}}>● Lidar</span><span style={{color:"#ba6817"}}>● Camera</span></div>
  </div>;
}
