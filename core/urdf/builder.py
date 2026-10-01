# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Bounded OBJ import, editable rigid-link model, kinematics and URDF bundle export."""
import io
import math
from typing import Annotated, Literal
import xml.etree.ElementTree as ET
import zipfile
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .model import Origin, origin_matrix

Vector = Annotated[list[float], Field(min_length=3, max_length=3)]
Triangle = Annotated[list[int], Field(min_length=3, max_length=3)]
Name = Annotated[str, Field(pattern=r'^[A-Za-z][A-Za-z0-9_]{0,63}$')]


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Part(Strict):
    id: Name
    name: str = Field(max_length=200)
    vertices: list[Vector] = Field(min_length=3, max_length=30000)
    faces: list[Triangle] = Field(min_length=1, max_length=20000)
    normals: list[list[Vector | None]] | None = Field(default=None, max_length=20000)
    smoothing: list[str | None] | None = Field(default=None, max_length=20000)

    @model_validator(mode='after')
    def valid(self):
        if self.normals is not None:
            if len(self.normals) != len(self.faces) or any(len(row) != 3 for row in self.normals):
                raise ValueError('Normals must have three corners per face')
            if any(not 0.999 <= math.hypot(*n) <= 1.001 for row in self.normals for n in row if n is not None):
                raise ValueError('Normals must be unit vectors')
        if self.smoothing is not None and (len(self.smoothing) != len(self.faces) or any(s is not None and len(s) > 90 for s in self.smoothing)):
            raise ValueError('Smoothing groups must match faces')
        if any(i < 0 or i >= len(self.vertices) for f in self.faces for i in f): raise ValueError('Mesh index outside vertex array')
        if any(abs(v) > 1e9 for point in self.vertices for v in point): raise ValueError('Mesh coordinates exceed supported range')
        return self


class Link(Strict):
    name: Name
    parts: list[str] = Field(default_factory=list, max_length=256)
    parent: str | None = None
    kind: Literal['fixed', 'continuous', 'revolute', 'prismatic'] = 'fixed'
    xyz: Vector = Field(default_factory=lambda: [0., 0., 0.])
    rpy: Vector = Field(default_factory=lambda: [0., 0., 0.])
    axis: Vector = Field(default_factory=lambda: [0., 0., 1.])
    lower: float = -1.57
    upper: float = 1.57
    effort: float = Field(default=1., gt=0, le=1e12)
    velocity: float = Field(default=1., gt=0, le=1e9)
    mass: float | None = Field(default=None, gt=0, le=1e12)
    collision: Literal['box', 'mesh', 'none'] = 'box'


class Model(Strict):
    format: Literal['pyrobot-model'] = 'pyrobot-model'
    version: Literal[1] = 1
    name: Name = 'my_robot'
    source_format: Literal['obj', 'step'] = 'obj'
    source_name: str | None = Field(default=None, max_length=200)
    source_unit: str | None = Field(default=None, max_length=40)
    import_notes: list[str] = Field(default_factory=list, max_length=8)
    scale: float = Field(default=1., gt=0, le=1000000)
    parts: list[Part] = Field(min_length=1, max_length=256)
    links: list[Link] = Field(min_length=1, max_length=128)

    @model_validator(mode='after')
    def valid(self):
        if sum(len(p.faces) for p in self.parts) > 20000 or sum(len(p.vertices) for p in self.parts) > 60000:
            raise ValueError('Model exceeds 20,000 triangles or 60,000 component vertices; simplify the source mesh')
        parts = {p.id for p in self.parts}
        links = {link.name: link for link in self.links}
        if len(parts) != len(self.parts) or len(links) != len(self.links): raise ValueError('Part IDs and link names must be unique')
        reserved = {'con','prn','aux','nul'} | {f'{prefix}{i}' for prefix in ('com','lpt') for i in range(1,10)}
        if any(name.lower() in reserved for name in links): raise ValueError('A link name is reserved as a Windows mesh filename')
        assigned = [p for link in self.links for p in link.parts]
        if any(abs(v)*self.scale > 1e6 for part in self.parts for point in part.vertices for v in point):
            raise ValueError('Scaled coordinates exceed one million metres; check source units')
        if set(assigned) != parts or len(assigned) != len(set(assigned)):
            raise ValueError('Assign every component to exactly one link')
        roots = [link.name for link in self.links if link.parent is None]
        if len(roots) != 1: raise ValueError('Choose exactly one root link')
        for link in self.links:
            seen = set()
            current = link
            while current.parent is not None:
                if current.name in seen: raise ValueError('Joint tree contains a cycle')
                seen.add(current.name)
                if current.parent not in links: raise ValueError(f'Missing parent for {current.name}')
                current = links[current.parent]
            if any(abs(v) > 1e6 for v in (*link.axis,*link.rpy,link.lower,link.upper)): raise ValueError('Joint values exceed supported range')
            if np.linalg.norm(link.axis) < 1e-9: raise ValueError(f'{link.name}: joint axis must be nonzero')
            if link.lower > link.upper: raise ValueError(f'{link.name}: lower limit exceeds upper limit')
            if link.kind in ('revolute','prismatic') and not link.lower <= 0 <= link.upper:
                raise ValueError(f'{link.name}: imported zero pose must lie inside joint limits')
            if any(abs(v) > 1e6 for v in link.xyz): raise ValueError('Link coordinates exceed supported range')
            if link.mass and not link.parts: raise ValueError('Empty frames cannot have estimated box inertia')
        return self


def triangulate(indices, vertices):
    """Ear clipping handles simple planar polygons, including concave OBJ faces."""
    if len(indices) < 3 or len(indices) > 64: raise ValueError('OBJ faces must have 3 to 64 corners')
    points = np.array([vertices[i] for i in indices])
    normal = np.sum(np.cross(points, np.roll(points, -1, axis=0)), axis=0)
    norm = np.linalg.norm(normal)
    if norm < 1e-12: raise ValueError('Degenerate OBJ polygon')
    if np.max(np.abs((points - points[0]) @ (normal / norm))) > max(1e-7, np.ptp(points, axis=0).max() * 1e-5):
        raise ValueError('Non-planar OBJ polygon; triangulate it in your CAD/mesh editor first')
    xy = np.delete(points, np.argmax(np.abs(normal)), axis=1)
    cross = lambda a, b: a[0]*b[1]-a[1]*b[0]
    sign = 1 if sum(cross(a,b) for a,b in zip(xy, np.roll(xy,-1,axis=0))) > 0 else -1
    pending = list(range(len(indices))); result = []
    while len(pending) > 3:
        for j, b in enumerate(pending):
            a, c = pending[j-1], pending[(j+1) % len(pending)]
            if sign*cross(xy[b]-xy[a],xy[c]-xy[b]) <= 1e-12: continue
            def inside(p):
                return all(sign*cross(y-x,xy[p]-x) >= -1e-12 for x,y in ((xy[a],xy[b]),(xy[b],xy[c]),(xy[c],xy[a])))
            if any(inside(p) for p in pending if p not in (a,b,c)): continue
            result.append([indices[a],indices[b],indices[c]]); pending.pop(j); break
        else: raise ValueError('Invalid or self-intersecting OBJ face; triangulate before import')
    result.append([indices[p] for p in pending])
    return result


def import_obj(text, split=True):
    if len(text.encode()) > 4*1024*1024: raise ValueError('OBJ exceeds 4 MiB')
    vertices, faces = [], []
    normals, corner_normals, smoothing = [], [], []
    smooth_group = None
    object_name, group_name = 'mesh', ''
    for number, raw in enumerate(text.splitlines(), 1):
        fields = raw.split('#',1)[0].split()
        if not fields: continue
        try:
            if fields[0] == 'v':
                if len(fields) < 4: raise ValueError('Vertex requires XYZ')
                xyz = [float(v) for v in fields[1:4]]
                if not all(math.isfinite(v) and abs(v) < 1e9 for v in xyz): raise ValueError('Invalid vertex coordinate')
                vertices.append(xyz)
                if len(vertices) > 30000: raise ValueError('More than 30,000 OBJ vertices')
            elif fields[0] == 'vn':
                n = [float(v) for v in fields[1:]]
                if len(n) != 3 or not all(math.isfinite(v) for v in n) or math.hypot(*n) < 1e-12:
                    raise ValueError('Invalid OBJ normal')
                normals.append([v / math.hypot(*n) for v in n])
                if len(normals) > 60000: raise ValueError('More than 60,000 OBJ normals')
            elif fields[0] == 's':
                smooth_group = fields[1][:90]
                if smooth_group in ('off', '0'): smooth_group = 'off'
            elif fields[0] == 'o':
                object_name, group_name = (' '.join(fields[1:]) or 'mesh')[:90], ''
            elif fields[0] == 'g': group_name = ' '.join(fields[1:])[:90]
            elif fields[0] == 'f':
                indices, face_normals = [], []
                for entry in fields[1:]:
                    index = int(entry.split('/')[0])
                    index = index-1 if index > 0 else len(vertices)+index if index < 0 else -1
                    if index < 0 or index >= len(vertices): raise ValueError('Invalid OBJ vertex reference')
                    indices.append(index)
                    tokens = entry.split('/')
                    n = None
                    if len(tokens) > 2 and tokens[2]:
                        ni = int(tokens[2])
                        ni = ni-1 if ni > 0 else len(normals)+ni if ni < 0 else -1
                        if ni < 0 or ni >= len(normals): raise ValueError('Invalid OBJ normal reference')
                        n = normals[ni]
                    face_normals.append(n)
                group = object_name + (':' + group_name if group_name else '')
                for corners in triangulate(list(range(len(indices))), [vertices[v] for v in indices]):
                    faces.append((group, [indices[c] for c in corners]))
                    corner_normals.append([face_normals[c] for c in corners])
                    smoothing.append(smooth_group)
                if len(faces) > 20000: raise ValueError('More than 20,000 triangles; simplify the mesh')
        except (ValueError, IndexError) as exc: raise ValueError(f'OBJ line {number}: {exc}') from exc
    if not faces: raise ValueError('OBJ contains no polygon faces')
    parents = list(range(len(faces)))
    def find(i):
        while parents[i] != i: parents[i] = parents[parents[i]]; i = parents[i]
        return i
    owners = {}
    for i, (label, triangle) in enumerate(faces):
        for vertex in triangle if split else [0]:
            key = (label, vertex)
            if key in owners: parents[find(i)] = find(owners[key])
            else: owners[key] = i
    groups = {}
    for i, (_, triangle) in enumerate(faces): groups.setdefault(find(i), []).append(i)
    if len(groups) > 256: raise ValueError('More than 256 loose components; import using object groups or repair disconnected geometry')
    parts = []
    for i, (first, face_ids) in enumerate(groups.items()):
        triangles = [faces[f][1] for f in face_ids]
        used = sorted({v for t in triangles for v in t}); lookup = {v:j for j,v in enumerate(used)}
        parts.append(Part(id=f'part_{i}', name=f'{faces[first][0]} ({i+1})', vertices=[vertices[v] for v in used], faces=[[lookup[v] for v in t] for t in triangles], normals=[corner_normals[f] for f in face_ids], smoothing=[smoothing[f] for f in face_ids]))
    return Model(parts=parts, links=[Link(name='base_link', parts=[p.id for p in parts])])


def poses(model, positions=None):
    positions = positions or {}
    links = {link.name:link for link in model.links}
    if set(positions)-set(links): raise ValueError('Preview references an unknown joint link')
    zero = {link.name:origin_matrix(Origin(tuple(link.xyz),tuple(link.rpy))) for link in model.links}
    moved = {}
    def solve(name):
        if name in moved: return moved[name]
        link = links[name]
        motion = np.eye(4)
        value = float(positions.get(name,0))
        if not math.isfinite(value): raise ValueError('Joint position must be finite')
        if link.kind in ('revolute','prismatic') and not link.lower <= value <= link.upper:
            raise ValueError(f'{name}: preview position outside joint limits')
        axis = np.array(link.axis)/np.linalg.norm(link.axis)
        if link.kind == 'prismatic': motion[:3,3] = axis * value
        elif link.kind in ('continuous','revolute'):
            x,y,z = axis; skew = np.array([[0,-z,y],[z,0,-x],[-y,x,0]])
            motion[:3,:3] = np.eye(3) + math.sin(value)*skew + (1-math.cos(value))*(skew@skew)
        moved[name] = zero[name] if link.parent is None else solve(link.parent) @ np.linalg.inv(zero[link.parent]) @ zero[name] @ motion
        return moved[name]
    for name in links: solve(name)
    return zero, moved


def preview(model, positions=None):
    zero, moved = poses(model, positions)
    owner = {part:link.name for link in model.links for part in link.parts}
    parts = []
    for part in model.parts:
        name = owner[part.id]
        matrix = moved[name] @ np.linalg.inv(zero[name])
        vertices = np.array(part.vertices)*model.scale
        transformed = vertices @ matrix[:3,:3].T + matrix[:3,3]
        normals = None if part.normals is None else [[None if n is None else (matrix[:3,:3] @ n).tolist() for n in row] for row in part.normals]
        parts.append({'id':part.id,'name':part.name,'link':name,'vertices':transformed.tolist(),'faces':part.faces,'normals':normals,'smoothing':part.smoothing})
    frames = []
    for link in model.links:
        rotation = moved[link.name][:3, :3]
        joint_axis = rotation @ (np.array(link.axis) / np.linalg.norm(link.axis))
        frames.append({
            'name': link.name,
            'xyz': moved[link.name][:3,3].tolist(),
            'axis': joint_axis.tolist(),
            'joint_type': link.kind,
            'x_axis': rotation[:,0].tolist(),
            'y_axis': rotation[:,1].tolist(),
            'z_axis': rotation[:,2].tolist(),
        })
    return {'parts':parts, 'frames':frames}


def rpy_from(matrix):
    pitch = math.asin(float(np.clip(-matrix[2,0],-1,1)))
    if abs(math.cos(pitch)) > 1e-8: return [math.atan2(matrix[2,1],matrix[2,2]),pitch,math.atan2(matrix[1,0],matrix[0,0])]
    return [0.,pitch,math.atan2(-matrix[0,1],matrix[1,1])]


def bundle(model):
    zero, _ = poses(model)
    robot = ET.Element('robot', name=model.name)
    meshes = {}; warnings = ['CAD material/texture finishes are not exported. Enter verified mass/inertia before physics use.'] if model.source_format == 'step' else ['OBJ materials/textures are not exported. Collision boxes and inertia are approximations, not CAD mass properties.']
    fmt = lambda values: ' '.join(f'{float(v):.12g}' for v in values)
    by_id = {p.id:p for p in model.parts}
    for link in model.links:
        element = ET.SubElement(robot,'link',name=link.name)
        triangles = []; all_vertices = []
        inverse = np.linalg.inv(zero[link.name])
        for part_id in link.parts:
            part = by_id[part_id]
            vertices = np.array(part.vertices)*model.scale @ inverse[:3,:3].T + inverse[:3,3]
            all_vertices.extend(vertices)
            triangles.extend(vertices[face] for face in part.faces)
        if triangles:
            path = f'meshes/{link.name}.stl'
            lines = ['solid link']
            for triangle in triangles:
                normal = np.cross(triangle[1]-triangle[0],triangle[2]-triangle[0]); norm = np.linalg.norm(normal)
                normal = normal/norm if norm > 0 else normal
                lines.extend([f'facet normal {fmt(normal)}','outer loop',*[f'vertex {fmt(v)}' for v in triangle],'endloop','endfacet'])
            lines.append('endsolid link'); meshes[path] = '\n'.join(lines)
            ET.SubElement(ET.SubElement(ET.SubElement(element,'visual'),'geometry'),'mesh',filename=path)
            points = np.array(all_vertices); low,high = points.min(axis=0),points.max(axis=0)
            size = np.maximum(high-low,1e-6); centre = (low+high)/2
            if link.collision == 'box':
                collision = ET.SubElement(element,'collision'); ET.SubElement(collision,'origin',xyz=fmt(centre),rpy='0 0 0')
                ET.SubElement(ET.SubElement(collision,'geometry'),'box',size=fmt(size))
            elif link.collision == 'mesh':
                collision = ET.SubElement(element,'collision'); ET.SubElement(collision,'origin',xyz='0 0 0',rpy='0 0 0')
                ET.SubElement(ET.SubElement(collision,'geometry'),'mesh',filename=path)
            if link.mass is not None:
                inertial = ET.SubElement(element,'inertial'); ET.SubElement(inertial,'origin',xyz=fmt(centre),rpy='0 0 0')
                ET.SubElement(inertial,'mass',value=str(link.mass))
                x,y,z = size; mass = link.mass/12
                ET.SubElement(inertial,'inertia',ixx=str(mass*(y*y+z*z)),iyy=str(mass*(x*x+z*z)),izz=str(mass*(x*x+y*y)),ixy='0',ixz='0',iyz='0')
            else: warnings.append(f'{link.name}: mass/inertia omitted; enter measured mass before physics use.')
        if link.parent:
            relative = np.linalg.inv(zero[link.parent]) @ zero[link.name]
            joint = ET.SubElement(robot,'joint',name=link.name+'_joint',type=link.kind)
            ET.SubElement(joint,'parent',link=link.parent); ET.SubElement(joint,'child',link=link.name)
            ET.SubElement(joint,'origin',xyz=fmt(relative[:3,3]),rpy=fmt(rpy_from(relative)))
            if link.kind != 'fixed':
                ET.SubElement(joint,'axis',xyz=fmt(np.array(link.axis)/np.linalg.norm(link.axis)))
                limits = {'effort':str(link.effort),'velocity':str(link.velocity)}
                if link.kind != 'continuous': limits.update(lower=str(link.lower),upper=str(link.upper))
                ET.SubElement(joint,'limit',**limits)
    ET.indent(robot)
    xml = ET.tostring(robot,encoding='unicode')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('robot.urdf',xml)
        archive.writestr('robot-builder.json',model.model_dump_json(indent=2))
        archive.writestr('README.txt','Extract all files together. Relative mesh paths are required.\n'+'\n'.join(warnings))
        for path, mesh in meshes.items(): archive.writestr(path,mesh)
    return stream.getvalue(), xml, warnings
