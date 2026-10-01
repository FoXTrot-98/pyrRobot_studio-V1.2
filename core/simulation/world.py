# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Deterministic planar kinematics, ray-cast lidar and a perspective camera.

This is a geometric simulator: no suspension, friction or full rigid-body physics.
"""
import math
import numpy as np
from .config import RobotConfiguration
from core.urdf.model import origin_matrix


BOUNDS = (-2.0, -2.0, 10.0, 8.0)
# x_min, y_min, x_max, y_max, height. Includes the room boundary.
OBSTACLES = [
    (-2.2, -2.2, 10.2, -2.0, 1.6), (-2.2, 8.0, 10.2, 8.2, 1.6),
    (-2.2, -2.0, -2.0, 8.0, 1.6), (10.0, -2.0, 10.2, 8.0, 1.6),
    (2.0, -1.0, 2.8, 3.5, 1.0), (5.0, 3.0, 6.0, 6.5, 1.3),
    (0.0, 5.0, 2.0, 6.0, 0.9), (7.5, 0.0, 8.5, 1.8, 1.1),
]


def wrap(angle):
    return (angle + math.pi) % (2 * math.pi) - math.pi


def advance(pose, distance, rotation):
    x, y, yaw = pose
    if abs(rotation) > 1e-9:
        radius = distance / rotation
        x += radius * (math.sin(yaw + rotation) - math.sin(yaw))
        y -= radius * (math.cos(yaw + rotation) - math.cos(yaw))
    else:
        x += distance * math.cos(yaw)
        y += distance * math.sin(yaw)
    return np.array([x, y, wrap(yaw + rotation)])


def sensor_pose(pose, offset):
    x, y, yaw = pose
    ox, oy, oyaw = offset
    return np.array([x + math.cos(yaw)*ox - math.sin(yaw)*oy,
                     y + math.sin(yaw)*ox + math.cos(yaw)*oy, wrap(yaw + oyaw)])


def raycast(pose, angles, maximum=9.0, obstacles=None):
    """First ray/axis-aligned-box intersection for each horizontal beam."""
    angles = np.asarray(angles) + pose[2]
    direction = np.stack([np.cos(angles), np.sin(angles)], axis=1)
    # Near-parallel rays use a tiny signed direction to avoid division by zero.
    safe = np.where(np.abs(direction) < 1e-12, 1e-12, direction)
    ranges = np.full(len(angles), maximum, dtype=float)
    indices = np.full(len(angles), -1, dtype=int)
    for index, box in enumerate(OBSTACLES if obstacles is None else obstacles):
        a = (np.array(box[:2]) - pose[:2]) / safe
        b = (np.array(box[2:4]) - pose[:2]) / safe
        enter, leave = np.minimum(a, b).max(axis=1), np.maximum(a, b).min(axis=1)
        hit = (leave >= np.maximum(enter, 0)) & (enter >= 0) & (enter < ranges)
        ranges[hit], indices[hit] = enter[hit], index
    return ranges, indices


def collision(pose, radius=.48, obstacles=None):
    for x0, y0, x1, y1, _ in OBSTACLES if obstacles is None else obstacles:
        closest = np.clip(pose[:2], [x0, y0], [x1, y1])
        if np.linalg.norm(pose[:2] - closest) < radius:
            return True
    return False


def camera_image(pose, camera_height=.42, width=240, height=144, obstacles=None):
    """Pinhole projection of vertical scene boxes, with depth shading."""
    focal = width / (2 * math.tan(math.radians(70) / 2))
    angles = np.arctan((width / 2 - np.arange(width)) / focal)
    obstacles = OBSTACLES if obstacles is None else obstacles
    ranges, hit = raycast(pose, angles, maximum=20, obstacles=obstacles)
    depth = np.maximum(ranges * np.cos(angles), .05)
    image = np.empty((height, width, 3), dtype=np.uint8)
    image[:height//2] = [174, 202, 223]
    image[height//2:] = [75, 85, 89]
    palette = np.array([[115, 140, 165], [138, 160, 175], [130, 150, 170], [130, 150, 170],
                        [225, 139, 61], [77, 172, 146], [184, 114, 170], [95, 145, 218]])
    for column in range(width):
        if hit[column] < 0:
            continue
        box_height = obstacles[hit[column]][4]
        top = max(0, int(height/2 - focal*(box_height-camera_height)/depth[column]))
        bottom = min(height, int(height/2 + focal*camera_height/depth[column]))
        image[top:bottom, column] = (palette[hit[column] % len(palette)] * max(.3, 1-depth[column]/25)).astype(np.uint8)
    return image


def robot_dimensions(model, configuration=None):
    """Derive drive and sensor geometry from the project's URDF."""
    if model is None:
        raise ValueError("Load the four-wheel robot URDF before starting simulation")
    drive = (configuration or RobotConfiguration()).drive
    try:
        wheels = [model.joints[name] for name in drive.left_joints + drive.right_joints]
    except KeyError as exc:
        raise ValueError(f"Missing configured wheel joint {exc.args[0]}") from exc
    centers, radii = [], []
    for joint in wheels:
        parent = model.static_transform(drive.base_frame, joint.parent)
        if parent is None or joint.joint_type not in ("continuous", "revolute"):
            raise ValueError(f"Wheel {joint.name} needs a rotating joint on a fixed mount")
        matrix = np.asarray(parent["matrix"]) @ origin_matrix(joint.origin)
        axis = matrix[:3,:3] @ np.asarray(joint.axis)
        if not np.allclose(axis, [0,1,0], atol=1e-5):
            raise ValueError(f"Wheel {joint.name} axis must point along base +Y for this drive model")
        centers.append(matrix[:3,3])
        geometry = model.links[joint.child].visual_geometry
        radii.append(drive.wheel_radius or float(geometry.get("radius", 0)))
    if min(radii) <= 0 or not np.allclose(radii, radii[0]):
        raise ValueError("Four-wheel differential drive requires equal positive wheel radii; set wheel_radius for mesh wheels")
    radius = radii[0]
    left, right = np.asarray(centers[:2]), np.asarray(centers[2:])
    track = float(left[:,1].mean() - right[:,1].mean())
    if track <= 0 or not np.allclose(left[:,1], left[0,1]) or not np.allclose(right[:,1], right[0,1]):
        raise ValueError("Wheel pairs must share lateral positions, with left wheels at larger Y")
    mounts = {}
    for role, name in (("lidar_link", drive.lidar_frame), ("camera_link", drive.camera_frame)):
        transform = model.static_transform(drive.base_frame, name)
        if transform is None:
            raise ValueError(f"{name} must have a fixed mount")
        if not np.allclose(transform["rpy"][:2], [0,0], atol=1e-5):
            raise ValueError(f"{name} must be level for the planar simulator")
        mounts[role] = [transform["xyz"][0], transform["xyz"][1], transform["rpy"][2]]
        mounts[role + "_height"] = transform["xyz"][2]
    return radius, track, mounts


class FourWheelSimulator:
    def __init__(self, radius=.12, track=.62, seed=7, configuration=None):
        self.configuration = configuration or RobotConfiguration()
        self.obstacles = self.configuration.environment.boxes()
        self.radius, self.track = radius, track
        self.pose = np.asarray(self.configuration.spawn_pose,dtype=float).copy()
        self.wheels = np.zeros(4)
        self.time = 0.0
        self.collisions = 0
        self.rng = np.random.default_rng(seed)

    def step(self, linear, angular, dt):
        linear, angular = np.clip(linear, -.8, .8), np.clip(angular, -1.5, 1.5)
        candidate = advance(self.pose, linear*dt, angular*dt)
        blocked = collision(candidate, self.configuration.drive.collision_radius, self.obstacles)
        if blocked:
            linear = angular = 0.0
            self.collisions += 1
        else:
            self.pose = candidate
        left = (linear-angular*self.track/2)*dt/self.radius
        right = (linear+angular*self.track/2)*dt/self.radius
        self.wheels += [left, left, right, right]
        self.time += dt
        return blocked

    def scan(self, offset, beams=360, noise=.005):
        angles = np.linspace(-math.pi, math.pi, beams, endpoint=False)
        ranges, hits = raycast(sensor_pose(self.pose, offset), angles, obstacles=self.obstacles)
        valid = hits >= 0
        ranges[valid] = np.clip(ranges[valid] + self.rng.normal(0, noise, valid.sum()), .05, 9.0)
        return {"ranges": ranges.tolist(), "angles": angles.tolist(), "hits": valid.tolist(),
                "range_max": 9.0, "offset": list(offset), "frame": self.configuration.drive.lidar_frame}
