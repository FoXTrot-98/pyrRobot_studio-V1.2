// SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
// SPDX-License-Identifier: Apache-2.0

import type { ModelPart, Vector3 } from '../types/modelBuilder';

const unit=(v:number[]):Vector3=>{const length=Math.hypot(...v)||1;return v.map(x=>x/length) as Vector3;};
const dot=(a:number[],b:number[])=>a.reduce((sum,v,i)=>sum+v*b[i],0);

// Corner normals keep CAD creases sharp; coincident export vertices can still shade together.
export function surfaceNormals(part:ModelPart, smooth:boolean):Vector3[][] {
  const weighted=part.faces.map(f=>{
    const [a,b,c]=f.map(i=>part.vertices[i]);
    const u=b.map((v,i)=>v-a[i]),v=c.map((v,i)=>v-a[i]);
    return [u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]];
  });
  const normals=weighted.map(unit);
  const adjacent=new Map<string,Set<number>>();
  const keys=part.vertices.map(v=>v.join(','));
  part.faces.forEach((f,i)=>f.forEach(v=>{const key=keys[v];if(!adjacent.has(key))adjacent.set(key,new Set());adjacent.get(key)!.add(i);}));
  return part.faces.map((f,i)=>f.map((v,c)=>{
    if(!smooth)return normals[i];
    const supplied=part.normals?.[i]?.[c];if(supplied)return supplied;
    const group=part.smoothing?.[i];if(group==='off')return normals[i];
    const sum=[0,0,0];
    for(const j of adjacent.get(keys[v])!){
      if(part.smoothing?.[j]!==group || dot(normals[i],normals[j])<Math.SQRT1_2)continue;
      weighted[j].forEach((n,k)=>sum[k]+=n);
    }
    return unit(sum);
  }));
}

export function drawSurface(canvas:HTMLCanvasElement, parts:ModelPart[], selected:string[], screen:(v:Vector3)=>number[], rotate:(v:Vector3)=>number[], smooth:boolean, wireframe:boolean):boolean {
  const gl=canvas.getContext('webgl',{antialias:true,alpha:true});if(!gl)return false;
  const shaders:WebGLShader[]=[];
  const buffers:WebGLBuffer[]=[];
  const program=gl.createProgram();if(!program)return false;
  try {
    const compile=(type:number,source:string)=>{
      const shader=gl.createShader(type);if(!shader)throw new Error('Shader allocation failed');shaders.push(shader);
      gl.shaderSource(shader,source);gl.compileShader(shader);
      if(!gl.getShaderParameter(shader,gl.COMPILE_STATUS))throw new Error('Shader compilation failed');
      gl.attachShader(program,shader);
    };
    compile(gl.VERTEX_SHADER,`attribute vec3 position; attribute vec3 normal; attribute vec3 color; varying vec3 n; varying vec3 c;
      void main(){gl_Position=vec4(position,1.0);n=normal;c=color;}`);
    compile(gl.FRAGMENT_SHADER,`precision mediump float; varying vec3 n; varying vec3 c; uniform float lines;
      void main(){vec3 norm=normalize(n);if(norm.z<0.0)norm=-norm;
      float light=0.38+0.62*max(0.0,dot(norm,normalize(vec3(-0.4,0.6,1.0))));
      gl_FragColor=vec4(mix(c*light,vec3(0.18,0.24,0.30),lines),1.0);}`);
    gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))return false;
    gl.useProgram(program);gl.viewport(0,0,canvas.width,canvas.height);
    gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);gl.enable(gl.DEPTH_TEST);
    let depth=0.001;for(const part of parts)for(const v of part.vertices)depth=Math.max(depth,Math.abs(screen(v)[2]));
    const data:number[]=[], edges:number[]=[];
    const palette=[[0.42,0.64,0.8],[0.52,0.7,0.56],[0.67,0.55,0.78],[0.76,0.63,0.44]];
    parts.forEach((part,index)=>{
      const normals=surfaceNormals(part,smooth),color=selected.includes(part.id)?[0.94,0.63,0.23]:palette[index%palette.length];
      part.faces.forEach((face,i)=>{
        const corners=face.map((v,c)=>{
          const p=screen(part.vertices[v]),n=rotate(normals[i][c]);
          return [p[0]/400-1,1-p[1]/250,-p[2]/(depth*1.01),n[0],-n[1],n[2],...(selected.includes(part.id)?color:part.colors?.[v]??color)];
        });
        corners.forEach(c=>data.push(...c));
        if(wireframe)for(let c=0;c<3;c++)edges.push(...corners[c],...corners[(c+1)%3]);
      });
    });
    const draw=(values:number[],mode:number)=>{
      const buffer=gl.createBuffer();if(!buffer)throw new Error('Buffer allocation failed');buffers.push(buffer);
      gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(values),gl.STATIC_DRAW);
      ['position','normal','color'].forEach((name,i)=>{const loc=gl.getAttribLocation(program,name);gl.enableVertexAttribArray(loc);gl.vertexAttribPointer(loc,3,gl.FLOAT,false,36,i*12);});
      gl.drawArrays(mode,0,values.length/9);
    };
    gl.uniform1f(gl.getUniformLocation(program,'lines'),0);
    gl.enable(gl.POLYGON_OFFSET_FILL);gl.polygonOffset(1,1);draw(data,gl.TRIANGLES);gl.disable(gl.POLYGON_OFFSET_FILL);
    if(wireframe){gl.uniform1f(gl.getUniformLocation(program,'lines'),1);draw(edges,gl.LINES);}
    return true;
  } catch {return false;} finally {buffers.forEach(b=>gl.deleteBuffer(b));shaders.forEach(s=>gl.deleteShader(s));gl.deleteProgram(program);}
}
