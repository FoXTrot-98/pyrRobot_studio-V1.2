"""Bounded, embedded robot meshes. No filesystem or URL resolution is performed."""
import io
import json
import math
import re
import zipfile
from typing import Annotated

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

Vector = Annotated[list[float], Field(min_length=3, max_length=3)]
Triangle = Annotated[list[int], Field(min_length=3, max_length=3)]


class MeshAsset(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    vertices: list[Vector] = Field(min_length=3, max_length=60000)
    faces: list[Triangle] = Field(min_length=1, max_length=20000)
    normals: list[Vector] = Field(min_length=3, max_length=60000)
    colors: list[Vector] = Field(min_length=3, max_length=60000)

    @model_validator(mode='after')
    def valid(self):
        if len(self.normals) != len(self.vertices) or len(self.colors) != len(self.vertices):
            raise ValueError('Mesh normals and colors must match vertices')
        if any(i < 0 or i >= len(self.vertices) for f in self.faces for i in f):
            raise ValueError('Mesh index outside vertex array')
        if any(abs(v) > 1e6 for p in self.vertices for v in p): raise ValueError('Mesh coordinates exceed supported range')
        if any(not .999 <= math.hypot(*n) <= 1.001 for n in self.normals): raise ValueError('Mesh normals must be unit vectors')
        if any(not 0 <= c <= 1 for row in self.colors for c in row): raise ValueError('Mesh colors must be between zero and one')
        return self


Assets = Annotated[dict[str, MeshAsset], Field(max_length=128)]


def validate_assets(assets):
    if sum(len(a.faces) for a in assets.values()) > 20000:
        raise ValueError('Robot assets exceed 20,000 triangles')
    if any(not re.fullmatch(r'meshes/[A-Za-z][A-Za-z0-9_]{0,63}\.stl', key) for key in assets):
        raise ValueError('Robot asset names must be relative meshes/<link>.stl identifiers')
    if len(json.dumps({k:v.model_dump() for k,v in assets.items()}, separators=(',', ':'))) > 6*1024*1024:
        raise ValueError('Embedded robot assets exceed 6 MiB; simplify the model')
    return assets


def attach_assets(model, assets):
    validate_assets(assets)
    referenced = {link.visual_mesh for link in model.links.values() if link.visual_mesh}
    if assets and set(assets) != referenced:
        raise ValueError('Embedded meshes must match all URDF visual mesh references')
    model.assets = assets
    return model


def corner_normals(part):
    vertices = np.asarray(part.vertices)
    triangles = vertices[np.asarray(part.faces)]
    weighted = np.cross(triangles[:,1]-triangles[:,0], triangles[:,2]-triangles[:,0])
    lengths = np.linalg.norm(weighted, axis=1)
    if np.any(lengths < 1e-15): raise ValueError('Degenerate mesh triangle; repair the source mesh')
    normals = weighted / lengths[:,None]
    adjacent = {}
    for i, face in enumerate(part.faces):
        for v in face: adjacent.setdefault(tuple(part.vertices[v]), set()).add(i)
    result = []
    for i, face in enumerate(part.faces):
        group = part.smoothing[i] if part.smoothing else None
        for c, v in enumerate(face):
            supplied = part.normals[i][c] if part.normals else None
            if supplied is not None: result.append(supplied); continue
            if group == 'off': result.append(normals[i]); continue
            neighbors = [j for j in adjacent[tuple(part.vertices[v])] if
                         (part.smoothing[j] if part.smoothing else None) == group and normals[i] @ normals[j] >= math.sqrt(.5)]
            normal = weighted[neighbors].sum(axis=0)
            result.append(normal / np.linalg.norm(normal))
    return np.asarray(result)


def builder_package(model):
    from .builder import bundle, poses
    _, xml, _ = bundle(model)
    zero, _ = poses(model)
    palette = [[.42,.64,.8],[.52,.7,.56],[.67,.55,.78],[.76,.63,.44]]
    assets = {}
    for link in model.links:
        inverse = np.linalg.inv(zero[link.name])
        vertices, normals, colors = [], [], []
        for index, part in enumerate(model.parts):
            if part.id not in link.parts: continue
            points = np.asarray(part.vertices)[np.asarray(part.faces)].reshape(-1,3)
            vertices.extend((points*model.scale @ inverse[:3,:3].T + inverse[:3,3]).tolist())
            normals.extend((corner_normals(part) @ inverse[:3,:3].T).tolist())
            colors.extend([palette[index % len(palette)]] * len(points))
        if vertices:
            assets[f'meshes/{link.name}.stl'] = MeshAsset(vertices=vertices, normals=normals, colors=colors,
                faces=[[i,i+1,i+2] for i in range(0,len(vertices),3)])
    validate_assets(assets)
    return {'robot_urdf':xml, 'robot_assets':{k:v.model_dump() for k,v in assets.items()}}


def read_builder_bundle(data):
    """Use the editable source included in builder ZIPs to retain smooth normals."""
    from .builder import Model
    if len(data) > 8*1024*1024: raise ValueError('Builder bundle exceeds 8 MiB')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            matches = [i for i in archive.infolist() if i.filename == 'robot-builder.json']
            if len(matches) != 1 or matches[0].file_size > 8*1024*1024:
                raise ValueError('Choose a Model Builder ZIP containing one robot-builder.json (up to 8 MiB)')
            return builder_package(Model.model_validate_json(archive.read(matches[0])))
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise ValueError('Invalid or encrypted Model Builder ZIP') from exc
