export type Vector3 = [number, number, number];
export interface ModelPart { id:string; name:string; vertices:Vector3[]; faces:number[][]; normals?:(Vector3|null)[][]|null; smoothing?:(string|null)[]|null; colors?:Vector3[]|null }
export interface ModelLink {
  name:string; parts:string[]; parent:string|null; kind:'fixed'|'continuous'|'revolute'|'prismatic';
  xyz:Vector3; rpy:Vector3; axis:Vector3; lower:number; upper:number; effort:number; velocity:number;
  mass:number|null; collision:'box'|'none';
}
export interface RobotBuilderModel { format:'pyrobot-model'; version:1; name:string; scale:number; parts:ModelPart[]; links:ModelLink[] }
export interface ModelPreview { parts:(ModelPart & {link:string})[]; frames:{name:string;xyz:Vector3;axis:Vector3}[] }
