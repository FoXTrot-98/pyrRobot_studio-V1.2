import { useEffect, useRef, useState } from 'react';
import { drawSurface } from './modelSurface';
import type { ModelPreview, Vector3 } from '../types/modelBuilder';

export function ModelViewport({preview, selected, onPick}: {preview:ModelPreview|null;selected:string[];onPick?:(id:string)=>void}) {
  const surface=useRef<HTMLCanvasElement>(null);
  const [smooth,setSmooth]=useState(true);
  const [wireframe,setWireframe]=useState(false);
  const [fallback,setFallback]=useState(false);
  const canvas=useRef<HTMLCanvasElement>(null);
  const faces=useRef<{id:string;points:number[][]}[]>([]);
  const [yaw,setYaw]=useState(35);
  const [pitch,setPitch]=useState(25);
  const [zoom,setZoom]=useState(1);
  useEffect(()=>{
    const ctx=canvas.current?.getContext('2d');if(!ctx)return;
    ctx.clearRect(0,0,800,500);
    if(!preview){const gl=surface.current?.getContext('webgl');gl?.clear(gl.COLOR_BUFFER_BIT);return;}
    const y=yaw*Math.PI/180,p=pitch*Math.PI/180;
    const project=(v:Vector3)=>{const x=v[0]*Math.cos(y)-v[1]*Math.sin(y),z=v[0]*Math.sin(y)+v[1]*Math.cos(y);return [x,z*Math.sin(p)-v[2]*Math.cos(p),z*Math.cos(p)+v[2]*Math.sin(p)];};
    const bounds=[Infinity,Infinity,-Infinity,-Infinity];
    for(const part of preview.parts)for(const vertex of part.vertices){const v=project(vertex);bounds[0]=Math.min(bounds[0],v[0]);bounds[1]=Math.min(bounds[1],v[1]);bounds[2]=Math.max(bounds[2],v[0]);bounds[3]=Math.max(bounds[3],v[1]);}
    const scale=Math.min(680/Math.max(.001,bounds[2]-bounds[0]),380/Math.max(.001,bounds[3]-bounds[1]))*zoom;
    const screen=(v:Vector3)=>{const a=project(v);return [400+(a[0]-(bounds[0]+bounds[2])/2)*scale,250+(a[1]-(bounds[1]+bounds[3])/2)*scale,a[2]];};
    const triangles=preview.parts.flatMap((part,index)=>part.faces.map(face=>({id:part.id,index,points:face.map(i=>screen(part.vertices[i]))}))).sort((a,b)=>a.points.reduce((s,p)=>s+p[2],0)-b.points.reduce((s,p)=>s+p[2],0));
    faces.current=triangles;
    const rendered=surface.current ? drawSurface(surface.current,preview.parts,selected,screen,project,smooth,wireframe) : false;
    setFallback(!rendered);
    if(!rendered)for(const t of triangles){ctx.beginPath();t.points.forEach((p,i)=>i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1]));ctx.closePath();ctx.fillStyle=selected.includes(t.id)?'#eea13a':`hsl(${205+t.index*43%150} 36% 64%)`;ctx.fill();ctx.strokeStyle='#34496355';ctx.lineWidth=.35;if(wireframe)ctx.stroke();}
    for(const frame of preview.frames){
      const start=screen(frame.xyz);
      const axes:[string,Vector3,string][]=[
        ['X',(frame.x_axis??[1,0,0]) as Vector3,'#b23a3a'],
        ['Y',(frame.y_axis??[0,1,0]) as Vector3,'#3c8c55'],
        ['Z',(frame.z_axis??[0,0,1]) as Vector3,'#3d67a8'],
      ];
      for(const [label,axis,stroke] of axes){
        const tip=screen(frame.xyz.map((v,i)=>v+axis[i]*.08) as Vector3);
        ctx.strokeStyle=stroke;ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(start[0],start[1]);ctx.lineTo(tip[0],tip[1]);ctx.stroke();
        ctx.fillStyle=stroke;ctx.font='11px sans-serif';ctx.fillText(label,tip[0]+2,tip[1]-2);
      }
      if(frame.joint_type && frame.joint_type!=='fixed'){
        const tip=screen(frame.xyz.map((v,i)=>v+frame.axis[i]*.12) as Vector3);
        ctx.strokeStyle='#922ba8';ctx.lineWidth=3;ctx.setLineDash([5,3]);
        ctx.beginPath();ctx.moveTo(start[0],start[1]);ctx.lineTo(tip[0],tip[1]);ctx.stroke();ctx.setLineDash([]);
        ctx.fillStyle='#922ba8';ctx.fillText('joint',tip[0]+4,tip[1]-4);
      }
      ctx.fillStyle='#1d304c';ctx.font='12px sans-serif';ctx.fillText(frame.name,start[0]+6,start[1]-7);
      ctx.beginPath();ctx.arc(start[0],start[1],3,0,Math.PI*2);ctx.fill();
    }
  },[preview,selected,yaw,pitch,zoom,smooth,wireframe]);
  return <div><div style={{position:'relative',background:'#edf2f8',borderRadius:10}}><canvas ref={surface} width={800} height={500} aria-hidden="true" style={{position:'absolute',inset:0,width:'100%',height:'100%',borderRadius:10}}/><canvas ref={canvas} width={800} height={500} aria-label="Interactive robot model preview" style={{position:'relative',display:'block',width:'100%',borderRadius:10}} onClick={event=>{
    if(!onPick)return;
    const target=event.currentTarget,rect=target.getBoundingClientRect();const x=(event.clientX-rect.left)*800/rect.width,y=(event.clientY-rect.top)*500/rect.height;const ctx=target.getContext('2d');if(!ctx)return;
    for(const face of [...faces.current].reverse()){ctx.beginPath();face.points.forEach((p,i)=>i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1]));ctx.closePath();if(ctx.isPointInPath(x,y)){onPick(face.id);break;}}
  }}/></div><div className="model-view-controls"><label><input type="checkbox" checked={smooth} onChange={e=>setSmooth(e.target.checked)}/>Smooth shading</label><label><input type="checkbox" checked={wireframe} onChange={e=>setWireframe(e.target.checked)}/>Wireframe</label><label>Orbit<input type="range" min="-180" max="180" value={yaw} onChange={e=>setYaw(Number(e.target.value))}/></label><label>Elevation<input type="range" min="-89" max="89" value={pitch} onChange={e=>setPitch(Number(e.target.value))}/></label><label>Zoom<input type="range" min=".5" max="3" step=".05" value={zoom} onChange={e=>setZoom(Number(e.target.value))}/></label></div><p>{fallback && 'Smooth rendering is unavailable in this browser; showing a basic preview. '}{onPick?'Click geometry to toggle component selection. ':''}XYZ axes show link orientation. Purple dashed lines show moving joint axes. View auto-fits the current pose.</p></div>;
}
