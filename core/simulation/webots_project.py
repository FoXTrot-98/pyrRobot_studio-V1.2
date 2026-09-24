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


def generate_project(directory, model, config, port, token):
    directory = Path(directory)
    worlds = directory/"worlds"
    controller = directory/"controllers/pyrobot_controller"
    worlds.mkdir(parents=True, exist_ok=True)
    controller.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT/"core/simulation/webots_controller.py", controller/"pyrobot_controller.py")
    (controller/"runtime.ini").write_text(f"[python]\nCOMMAND = {sys.executable}\n", encoding="utf-8")
    radius, track, mounts = robot_dimensions(model, config)
    drive = config.drive
    geometry = model.links[drive.base_frame].visual_geometry
    if geometry.get("type") != "box":
        raise ValueError("Webots reference exporter currently requires a box visual on the base frame")
    body_size = [float(v) for v in geometry["size"].split()]
    body_origin = model.links[drive.base_frame].visual_origin
    if not np.allclose(body_origin.rpy, 0):
        raise ValueError("Webots base box visual must be axis-aligned")
    children = [f"Pose {{ translation {vector(body_origin.xyz)} children [ {box(body_size)} ] }}"]
    for name in drive.left_joints + drive.right_joints:
        joint = model.joints[name]
        transform = np.asarray(model.static_transform(drive.base_frame, joint.parent)["matrix"]) @ origin_matrix(joint.origin)
        xyz = vector(transform[:3,3])
        wheel_geo = model.links[joint.child].visual_geometry
        width = float(wheel_geo.get("length", .1))
        wheel_shape = f"Pose {{ rotation 1 0 0 1.570796327 children [ Shape {{ appearance PBRAppearance {{ baseColor 0.08 0.09 0.1 roughness 1 metalness 0 }} geometry Cylinder {{ radius {radius} height {width} subdivision 24 }} }} ] }}"
        children.append(f'''HingeJoint {{
          jointParameters HingeJointParameters {{ anchor {xyz} axis 0 1 0 dampingConstant 0.02 }}
          device [ RotationalMotor {{ name {json.dumps(name)} maxVelocity 20 maxTorque 8 }}
                   PositionSensor {{ name {json.dumps(name + "_encoder")} }} ]
          endPoint Solid {{ translation {xyz} name {json.dumps(joint.child)}
            children [ {wheel_shape} ] contactMaterial "wheel"
            boundingObject Pose {{ rotation 1 0 0 1.570796327 children [ Cylinder {{ radius {radius} height {width} }} ] }}
            physics Physics {{ density -1 mass 0.3 }} }} }}''')
    lidar = mounts["lidar_link"]
    camera = mounts["camera_link"]
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
  contactProperties [ ContactProperties {{ material1 "wheel" material2 "floor" coulombFriction [ 0.8 ] forceDependentSlip [ 0.02 ] }} ] }}
Viewpoint {{ orientation {vector(orientation)} position {vector(eye)} }}
Background {{ skyColor [ 0.65 0.78 0.9 ] }}
DirectionalLight {{ direction -0.3 0.4 -1 intensity 1 }}
Solid {{ translation {(a+c)/2} {(b+d)/2} -0.05 name "floor" contactMaterial "floor"
  children [ {box([c-a+1,d-b+1,.1], "0.55 0.6 0.63")} ] boundingObject Box {{ size {c-a+1} {d-b+1} 0.1 }} }}
{' '.join(obstacles)}
DEF PYROBOT Robot {{ translation 0 0 0.002 name "PyRobot four wheel" supervisor TRUE
  controller "pyrobot_controller" controllerArgs [ "{port}" "{token}" ]
  children [ {' '.join(children)} ]
  boundingObject Pose {{ translation {vector(body_origin.xyz)} children [ Box {{ size {vector(body_size)} }} ] }}
  physics Physics {{ density -1 mass 8 centerOfMass [ {vector(body_origin.xyz)} ] }} }}
'''
    path = worlds/"pyrobot.wbt"
    path.write_text(world, encoding="utf-8")
    (controller/"robot.json").write_text(json.dumps({"radius": radius, "track": track,
        "joints": drive.left_joints+drive.right_joints, "mounts": mounts,
        "config": config.model_dump()}), encoding="utf-8")
    return path
