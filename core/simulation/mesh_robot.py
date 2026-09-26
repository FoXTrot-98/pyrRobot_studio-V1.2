"""Shared visual geometry and supported custom four-wheel checks."""
import math
import numpy as np
from core.urdf.model import origin_matrix
from .world import robot_dimensions


def mesh_data(model, link):
    asset = model.assets.get(link.visual_mesh)
    if asset is None: raise ValueError(f'{link.name}: mesh is missing; open the Model Builder ZIP in Robot setup')
    scale = np.array([float(v) for v in link.visual_geometry.get('scale','1 1 1').split()])
    if scale.shape != (3,) or not np.all(np.isfinite(scale)) or np.any(scale <= 0):
        raise ValueError(f'{link.name}: mesh scale needs three positive finite values')
    normals = np.asarray(asset.normals)/scale
    normals /= np.linalg.norm(normals, axis=1)[:,None]
    return np.asarray(asset.vertices)*scale, asset.faces, normals, asset.colors


def visual_points(model, link):
    geometry = link.visual_geometry
    kind = geometry.get('type')
    if kind == 'mesh': points = mesh_data(model, link)[0]
    elif kind in ('box','cylinder'):
        size = np.array([float(v) for v in geometry['size'].split()]) if kind == 'box' else np.array([2*float(geometry['radius']),2*float(geometry['radius']),float(geometry['length'])])
        if size.shape != (3,) or not np.all(np.isfinite(size)) or np.any(size <= 0): raise ValueError(f'{link.name}: invalid visual dimensions')
        points = np.array([[x,y,z] for x in (-.5,.5) for y in (-.5,.5) for z in (-.5,.5)])*size
    elif not kind: return np.empty((0,3))
    else: raise ValueError(f'{link.name}: {kind} visuals are not supported by this simulator')
    transform = origin_matrix(link.visual_origin)
    return points @ transform[:3,:3].T + transform[:3,3]


def validate_simulation_model(model, config):
    robot_dimensions(model, config)
    wheel_names = set(config.drive.left_joints + config.drive.right_joints)
    for joint in model.joints.values():
        if joint.joint_type != 'fixed' and joint.name not in wheel_names:
            raise ValueError(f'{joint.name}: simulation supports only the four wheel joints; fix other joints first')
    for link in model.links.values():
        if link.visual_geometry.get('type') == 'mesh': mesh_data(model,link)
    # Builder meshes need a deliberate wheel radius and a grounded zero pose.
    if model.assets:
        radius, _, _ = robot_dimensions(model,config)
        for name in wheel_names:
            joint = model.joints[name]
            parent = model.static_transform(config.drive.base_frame,joint.parent)
            matrix = np.asarray(parent['matrix']) @ origin_matrix(joint.origin)
            if not math.isclose(matrix[2,3],radius,abs_tol=.002):
                raise ValueError(f'{name}: wheel centre height must equal the wheel radius; set the base frame at ground level')
        base_chain = model.path_to_root(config.drive.base_frame)
        if any(j.joint_type != 'fixed' for j in base_chain): raise ValueError('Base frame must have a fixed path to the root')


def collision_body(model, config):
    validate_simulation_model(model,config)
    points = []
    for name, link in model.links.items():
        transform = model.static_transform(config.drive.base_frame,name)
        if transform is None: continue
        local = visual_points(model,link)
        if len(local):
            matrix = np.asarray(transform['matrix'])
            points.extend(local @ matrix[:3,:3].T + matrix[:3,3])
    if not points: raise ValueError('The robot needs body geometry fixed to its base frame')
    points = np.asarray(points)
    low, high = points.min(axis=0),points.max(axis=0)
    if model.assets and low[2] <= 0: raise ValueError('Body collision box touches the ground; raise the body above the base frame')
    return (low+high)/2, np.maximum(high-low,1e-6)


def wheel_width(model, joint, transform):
    points = visual_points(model,model.links[joint.child])
    if not len(points): return .1
    points = points @ transform[:3,:3].T
    return max(.001,float(np.ptp(points[:,1])))
