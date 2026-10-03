# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Generate an offline Webots world from the configured reference URDF."""
import json
import os
from pathlib import Path
import shutil
import sys
import cv2
import numpy as np
from core.urdf.model import origin_matrix
from .world import robot_dimensions
from .mesh_robot import collision_body, mesh_data, wheel_width
from .wheel_contact import wheel_contact_properties

ROOT = Path(__file__).resolve().parents[2]


def find_webots(explicit=""):
    candidates = [explicit, os.environ.get("WEBOTS_EXECUTABLE", ""), shutil.which("webots") or "",
        str(ROOT/".tools/Webots/msys64/mingw64/bin/webots.exe"), str(ROOT/".tools/Webots/webots.exe"),
        "C:/Program Files/Webots/msys64/mingw64/bin/webots.exe", "C:/Program Files/Webots/webots.exe",
        "/usr/local/webots/webots", "/Applications/Webots.app/Contents/MacOS/webots"]
    home = os.environ.get("WEBOTS_HOME")
    if home:
        candidates += [str(Path(home)/"webots"), str(Path(home)/"msys64/mingw64/bin/webots.exe")]
    return next((str(Path(p).resolve()) for p in candidates if p and Path(p).is_file()), None)


def vector(values):
    return " ".join(f"{float(x):.9g}" for x in values)


def box(size, color="0.35 0.5 0.65"):
    return f"Shape {{ appearance PBRAppearance {{ baseColor {color} roughness 0.8 metalness 0 }} geometry Box {{ size {vector(size)} }} }}"


def rotation_text(matrix):
    rotation, _ = cv2.Rodrigues(np.asarray(matrix,dtype=float))
    angle = float(np.linalg.norm(rotation))
    return vector([*(rotation[:,0]/angle),angle]) if angle > 1e-10 else '0 0 1 0'


def visual_shape(model,link,frame):
    geometry = link.visual_geometry
    kind = geometry.get('type')
    if not kind: return ''
    transform = frame @ origin_matrix(link.visual_origin)
    color = vector(link.color[:3])
    if kind == 'mesh':
        vertices, faces, normals, colors = mesh_data(model,link)
        # Webots IndexedFaceSet has no vertex-color field. Builder components
        # have constant triangle colors, so material groups preserve them exactly.
        groups = {}
        for face in faces:
            color = tuple(np.mean([colors[v] for v in face],axis=0))
            groups.setdefault(color,[]).append(face)
        shapes = []
        for color, triangles in groups.items():
            used = sorted({v for face in triangles for v in face})
            lookup = {v:i for i,v in enumerate(used)}
            points = ', '.join(vector(vertices[v]) for v in used)
            indices = ', '.join(' '.join(map(str,[*(lookup[v] for v in f),-1])) for f in triangles)
            normal_text = ', '.join(vector(normals[v]) for v in used)
            mesh = f'IndexedFaceSet {{ coord Coordinate {{ point [ {points} ] }} coordIndex [ {indices} ] normal Normal {{ vector [ {normal_text} ] }} normalPerVertex TRUE }}'
            shapes.append(f'Shape {{ appearance PBRAppearance {{ baseColor {vector(color)} roughness 0.8 metalness 0 }} geometry {mesh} }}')
        return f'Pose {{ translation {vector(transform[:3,3])} rotation {rotation_text(transform[:3,:3])} children [ {" ".join(shapes)} ] }}'
    elif kind == 'box': shape = f'Box {{ size {geometry["size"]} }}'
    elif kind == 'cylinder': shape = f'Cylinder {{ radius {float(geometry["radius"])} height {float(geometry["length"])} subdivision 32 }}'
    else: raise ValueError(f'{link.name}: unsupported Webots visual {kind}')
    return f'Pose {{ translation {vector(transform[:3,3])} rotation {rotation_text(transform[:3,:3])} children [ Shape {{ appearance PBRAppearance {{ baseColor {color} roughness 0.8 metalness 0 }} geometry {shape} }} ] }}'


def overview_viewpoint(bounds):
    """Webots looks along local +X, with local +Z up (ENU convention)."""
    a, b, c, d = bounds
    target = np.array([(a+c)/2, (b+d)/2, 0.])
    span = max(c-a, d-b)
    position = target + np.array([.9, -1.2, 1.2])*span
    forward = target-position
    forward /= np.linalg.norm(forward)
    left = np.cross([0., 0., 1.], forward)
    left /= np.linalg.norm(left)
    up = np.cross(forward, left)
    rotation, _ = cv2.Rodrigues(np.column_stack([forward, left, up]))
    angle = float(np.linalg.norm(rotation))
    return position, [*(rotation[:, 0]/angle), angle]


def generate_project(directory, model, config, port, token, executable="", placement_preview=False):
    directory = Path(directory)
    worlds = directory/"worlds"
    controller = directory/"controllers/pyrobot_controller"
    worlds.mkdir(parents=True, exist_ok=True)
    controller.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT/"core/simulation/webots_controller.py", controller/"pyrobot_controller.py")
    shutil.copyfile(ROOT/"core/simulation/placement_validation.py", controller/"placement_validation.py")
    shutil.copyfile(ROOT/"core/simulation/placement_search.py", controller/"placement_search.py")
    (controller/"runtime.ini").write_text(f"[python]\nCOMMAND = {sys.executable}\n", encoding="utf-8")
    radius, track, mounts = robot_dimensions(model, config)
    drive = config.drive
    physics = config.physics
    body_center, body_size = collision_body(model,config)
    children = []
    for link_name, link in model.links.items():
        transform = model.static_transform(drive.base_frame,link_name)
        if transform is not None:
            children.append(visual_shape(model,link,np.asarray(transform['matrix'])))
    for wheel_index, name in enumerate(drive.left_joints + drive.right_joints):
        joint = model.joints[name]
        transform = np.asarray(model.static_transform(drive.base_frame, joint.parent)["matrix"]) @ origin_matrix(joint.origin)
        xyz = vector(transform[:3,3])
        width = wheel_width(model,joint,transform)
        wheel_shape = []
        for link_name, link in model.links.items():
            fixed = model.static_transform(joint.child,link_name)
            if fixed is not None:
                wheel_shape.append(visual_shape(model,link,np.asarray(fixed['matrix'])))
        wheel_shape = ' '.join(wheel_shape)
        rotation = rotation_text(transform[:3,:3])
        children.append(f'''HingeJoint {{
          jointParameters HingeJointParameters {{ anchor {xyz} axis 0 1 0 dampingConstant {physics.wheel_damping:g} }}
          device [ RotationalMotor {{ name {json.dumps(name)} maxVelocity {physics.motor_max_velocity:g} maxTorque {physics.motor_max_torque:g} }}
                   PositionSensor {{ name {json.dumps(name + "_encoder")} }} ]
          endPoint DEF PYROBOT_WHEEL_{wheel_index} Solid {{ translation {xyz} rotation {rotation} name {json.dumps(joint.child)}
            children [ {wheel_shape} ] contactMaterial "wheel"
            boundingObject Pose {{ rotation {rotation_text(transform[:3,:3].T @ np.array([[1,0,0],[0,0,-1],[0,1,0]]))} children [ Cylinder {{ radius {radius} height {width} }} ] }}
            physics Physics {{ density -1 mass {physics.wheel_mass:g} }} }} }}''')
    lidar = mounts["lidar_link"]
    camera = mounts["camera_link"]
    children.append('Gyro { name "imu_gyro" xAxis FALSE yAxis FALSE zAxis TRUE }')
    children += [f'''Lidar {{ translation {lidar[0]} {lidar[1]} {mounts['lidar_link_height']}
        rotation 0 0 1 {lidar[2]} name "lidar" horizontalResolution 360 fieldOfView 6.283185307
        verticalFieldOfView 0.03 numberOfLayers 1 minRange 0.05 maxRange 9 noise 0.0005 }}''',
        f'''Camera {{ translation {camera[0]} {camera[1]} {mounts['camera_link_height']}
        rotation 0 0 1 {camera[2]} name "camera" width 240 height 144 fieldOfView 1.221730476 near 0.02 }}''']
    a,b,c,d = config.environment.bounds
    eye, orientation = overview_viewpoint(config.environment.bounds)
    obstacles = []
    for i, (x0,y0,x1,y1,height) in enumerate(config.environment.boxes()):
        size = [x1-x0, y1-y0, height]
        obstacles.append(f'''Solid {{ translation {(x0+x1)/2} {(y0+y1)/2} {height/2}
          name "obstacle_{i}" children [ {box(size, "0.75 0.45 0.2")} ]
          boundingObject Box {{ size {vector(size)} }} }}''')
    world = f'''#VRML_SIM R2025a utf8
WorldInfo {{ basicTimeStep 20 coordinateSystem "ENU"
  contactProperties [ {wheel_contact_properties('wheel', 'floor', physics)} ] }}
Viewpoint {{ orientation {vector(orientation)} position {vector(eye)} }}
Background {{ skyColor [ 0.65 0.78 0.9 ] }}
DirectionalLight {{ direction -0.3 0.4 -1 intensity 1 }}
Solid {{ translation {(a+c)/2} {(b+d)/2} -0.05 name "floor" contactMaterial "floor"
  children [ {box([c-a+1,d-b+1,.1], "0.55 0.6 0.63")} ] boundingObject Box {{ size {c-a+1} {d-b+1} 0.1 }} }}
{' '.join(obstacles)}
DEF PYROBOT Robot {{ translation {config.spawn_pose[0]} {config.spawn_pose[1]} {config.spawn_height} rotation 0 0 1 {config.spawn_pose[2]} name "PyRobot four wheel" supervisor TRUE
  controller "pyrobot_controller" controllerArgs [ "{port}" "{token}" ]
  children [ {' '.join(children)} ]
  boundingObject Pose {{ translation {vector(body_center)} children [ Box {{ size {vector(body_size)} }} ] }}
  physics Physics {{ density -1 mass {physics.body_mass:g} centerOfMass [ {vector(body_center)} ] }} }}
'''
    path = worlds/"pyrobot.wbt"
    if config.webots_world:
        from core.simulation.external_world import compose
        world=compose(config.webots_world,world,executable,config.webots_world_hash,physics)
        (Path(directory)/'SOURCE.txt').write_text(f'Source world: {config.webots_world}\nSHA256: {config.webots_world_hash}\nExisting top-level robots replaced. Relative assets reference the original project.\n',encoding='utf-8')
    path.write_text(world, encoding="utf-8")
    (controller/"robot.json").write_text(json.dumps({"radius": radius, "track": track,
        "joints": drive.left_joints+drive.right_joints, "mounts": mounts,
        "config": config.model_dump(), "placement_preview": placement_preview}), encoding="utf-8")
    return path
