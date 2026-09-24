"""Draft robot setup: inspect and validate before atomically replacing a project."""
import hashlib
import json
import math
from pathlib import Path
from typing import Literal
import xml.etree.ElementTree as ET

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from core.urdf.model import parse_urdf, origin_matrix
from core.simulation.config import RobotConfiguration
from core.simulation.world import robot_dimensions
from .project import ProjectDocument, Position, export_project, prepare_project
from .graph import GraphError

EXAMPLE = Path(__file__).resolve().parents[2]/'examples/four-wheel'


class SetupRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    robot_urdf: str = Field(min_length=1, max_length=4*1024*1024)
    robot_config: RobotConfiguration
    name: str = Field(min_length=1, max_length=200)
    target: Literal['configure', 'builtin', 'webots']
    revision: str
    positions: dict[str, Position] = Field(default_factory=dict)


def revision(runtime):
    state = {'graph': runtime.graph.to_dict(), 'xml': runtime.robot_xml,
             'config': runtime.graph.robot_config.model_dump(), 'name': runtime.name}
    # Health and execution identity do not change the editable configuration.
    state['graph'] = {key: state['graph'][key] for key in ('nodes', 'connections')}
    for node in state['graph']['nodes']:
        node.pop('state', None); node.pop('error', None)
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()


def checked_model(xml):
    root = ET.fromstring(xml)
    if root.tag != 'robot': raise ValueError('Choose a URDF file with a robot root element')
    for tag in ('link', 'joint'):
        names = [element.get('name') for element in root.findall(tag)]
        if any(not name for name in names) or len(names) != len(set(names)):
            raise ValueError(f'Every {tag} must have a unique, nonempty name')
    if not root.findall('link'): raise ValueError('The URDF has no links')
    if len(root.findall('link')) > 512: raise ValueError('Setup preview supports at most 512 links')
    model = parse_urdf(xml)
    children = set()
    for joint in model.joints.values():
        if joint.parent not in model.links or joint.child not in model.links:
            raise ValueError(f'Joint {joint.name} references a missing link')
        if joint.child in children: raise ValueError(f'Link {joint.child} has multiple parent joints')
        children.add(joint.child)
        for vector in (joint.origin.xyz, joint.origin.rpy, joint.axis):
            if len(vector) != 3 or not all(math.isfinite(v) for v in vector):
                raise ValueError(f'Joint {joint.name} needs finite three-component origins and axes')
    roots = set(model.links)-children
    if len(roots) != 1: raise ValueError('The URDF must contain one connected robot tree')
    for name, link in model.links.items():
        chain = model.path_to_root(name)
        if (chain[0].parent if chain else name) not in roots:
            raise ValueError('The URDF contains disconnected links')
        for vector in (link.visual_origin.xyz, link.visual_origin.rpy):
            if len(vector) != 3 or not all(math.isfinite(v) for v in vector):
                raise ValueError(f'Link {name} has an invalid visual origin')
    return model, next(iter(roots))


def inspect_robot(xml):
    model, root = checked_model(xml)
    transforms = {}
    links, warnings = [], []
    for name, link in model.links.items():
        matrix = np.eye(4)
        for joint in model.path_to_root(name): matrix = matrix @ origin_matrix(joint.origin)
        transforms[name] = matrix
        visual = matrix @ origin_matrix(link.visual_origin)
        shape = link.visual_geometry
        vertices, faces = [], []
        if shape.get('type') == 'box':
            size = np.array([float(v) for v in shape['size'].split()])
            if len(size) != 3 or not np.all(np.isfinite(size)) or np.any(size <= 0):
                raise ValueError(f'Link {name} needs three positive box dimensions')
            vertices = [[x,y,z] for z in (-.5,.5) for y in (-.5,.5) for x in (-.5,.5)]
            vertices = np.array(vertices)*size
            faces = [[0,1,3,2],[4,6,7,5],[0,4,5,1],[2,3,7,6],[0,2,6,4],[1,5,7,3]]
        elif shape.get('type') == 'cylinder':
            radius, length = float(shape['radius']), float(shape['length'])
            if not all(math.isfinite(v) and v > 0 for v in (radius,length)):
                raise ValueError(f'Link {name} needs positive cylinder dimensions')
            vertices = [[radius*math.cos(i*math.pi/6),radius*math.sin(i*math.pi/6),z] for z in (-length/2,length/2) for i in range(12)]
            faces = [list(range(12)),list(range(12,24))]+[[i,(i+1)%12,(i+1)%12+12,i+12] for i in range(12)]
        elif shape:
            warnings.append(f'{name}: {shape.get("type")} visual shown as a frame marker in this preview.')
        if len(vertices):
            vertices = (np.asarray(vertices) @ visual[:3,:3].T+visual[:3,3]).tolist()
        links.append({'name':name, 'xyz':matrix[:3,3].tolist(), 'vertices':vertices, 'faces':faces})
    config = RobotConfiguration().model_dump()
    drive = config['drive']
    drive['base_frame'] = 'base_link' if 'base_link' in model.links else root
    base_inverse = np.linalg.inv(transforms[drive['base_frame']])
    rotating = [j for j in model.joints.values() if j.joint_type in ('continuous','revolute')]
    wheels = {j.name: (base_inverse @ transforms[j.child])[:3,3] for j in rotating}
    for side, sign in (('left',1),('right',-1)):
        candidates = [j for j in rotating if wheels[j.name][1]*sign > 0 and
                      ('wheel' in j.name.lower() or model.links[j.child].visual_geometry.get('type') == 'cylinder')]
        candidates.sort(key=lambda j: -wheels[j.name][0])
        drive[f'{side}_joints'] = [j.name for j in candidates] if len(candidates)==2 else ['', '']
    for role, terms in (('lidar',('lidar','laser')),('camera',('camera',))):
        candidates = [name for name in model.links if any(term in name.lower() for term in terms) and 'optical' not in name.lower()]
        preferred = role+'_link'
        drive[role+'_frame'] = preferred if preferred in candidates else candidates[0] if len(candidates)==1 else ''
    return {'name':model.name,'root':root,'links':links,
            'joints':[{'name':j.name,'type':j.joint_type,'parent':j.parent,'child':j.child} for j in model.joints.values()],
            'suggested_config':config,'warnings':warnings}


def draft_project(runtime, request):
    if runtime.graph.to_dict()['running']: raise GraphError('Stop the graph before applying robot setup')
    if request.revision != revision(runtime): raise GraphError('The project changed while setup was open. Close and reopen Robot setup to review the latest project.')
    model, _ = checked_model(request.robot_urdf)
    radius, track, mounts = robot_dimensions(model, request.robot_config)
    if request.target == 'configure':
        document = export_project(runtime.graph, runtime.registry, request.name, request.robot_urdf,
                                  {k:v.model_dump() for k,v in request.positions.items()})
        document.robot_config = request.robot_config
    else:
        filename = 'webots.pyrobot.json' if request.target=='webots' else 'teleoperation.pyrobot.json'
        document = ProjectDocument.model_validate_json((EXAMPLE/filename).read_text(encoding='utf-8'))
        document.name, document.robot_urdf, document.robot_config = request.name, request.robot_urdf, request.robot_config
        for node in document.nodes:
            node.plugin_version = runtime.registry.get(node.plugin_id).manifest.version
            if node.plugin_id == 'pyrobot.navigation.astar': node.params.update(goal_x=0., goal_y=0., enabled=False, waypoints=[])
    for node in document.nodes:
        if node.plugin_id in ('pyrobot.sim.webots','pyrobot.sim.four_wheel'):
            node.urdf_link = request.robot_config.drive.base_frame
        if node.plugin_id == 'pyrobot.sim.webots':
            link = model.links[request.robot_config.drive.base_frame]
            if link.visual_geometry.get('type') != 'box' or not np.allclose(link.visual_origin.rpy, 0):
                raise ValueError('Webots currently requires an axis-aligned box visual on the base frame')
    candidate, _ = prepare_project(document, runtime.bus, runtime.registry)
    try:
        # Configuration errors are blockers; unfinished wiring is allowed when
        # retaining an existing graph, and is reported as a review warning.
        for instance in candidate.nodes.values(): instance.node_obj.validate_configuration()
        diagnostics = candidate.preflight()
        if request.target != 'configure' and diagnostics:
            raise GraphError('; '.join(item['message'] for item in diagnostics))
    finally:
        candidate.close()
    return document, {'wheel_radius':radius,'track':track,'mounts':mounts,
                      'node_count':len(document.nodes),'connection_count':len(document.connections),
                      'warnings':[item['message'] for item in diagnostics]}
