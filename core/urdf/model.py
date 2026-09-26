"""
URDF engine.

Parses a robot's URDF (and Xacro, via pre-processing through the `xacro`
tool if available) into a RobotModel: a queryable kinematic tree of links
and joints, including sensor mount frames, that becomes the system's
single source of truth for robot configuration.

Instead of hand-written per-robot YAML config, plugins that declare
`requires_urdf_link=True` in their manifest (see sdk/pyrobot_plugin/manifest.py)
get offered a dropdown of real link names from the loaded URDF, and can
query that link's static transform relative to any other link (e.g. "give
me lidar_link's transform relative to base_link") directly from this model.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Origin:
    xyz: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rpy: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass
class Link:
    name: str
    visual_mesh: Optional[str] = None
    collision_mesh: Optional[str] = None
    inertial_mass: Optional[float] = None
    visual_geometry: dict = field(default_factory=dict)
    visual_origin: Origin = field(default_factory=Origin)
    color: tuple = (0.4, 0.5, 0.7, 1.0)


@dataclass
class Joint:
    name: str
    joint_type: str  # revolute, prismatic, fixed, continuous, floating, planar
    parent: str
    child: str
    origin: Origin = field(default_factory=Origin)
    axis: tuple[float, float, float] = (0.0, 0.0, 1.0)
    limit_lower: Optional[float] = None
    limit_upper: Optional[float] = None
    limit_effort: Optional[float] = None
    limit_velocity: Optional[float] = None


@dataclass
class RobotModel:
    name: str
    links: dict[str, Link] = field(default_factory=dict)
    joints: dict[str, Joint] = field(default_factory=dict)
    assets: dict = field(default_factory=dict)

    def link_names(self) -> list[str]:
        return sorted(self.links.keys())

    def children_of(self, link_name: str) -> list[Joint]:
        return [j for j in self.joints.values() if j.parent == link_name]

    def parent_joint_of(self, link_name: str) -> Optional[Joint]:
        for j in self.joints.values():
            if j.child == link_name:
                return j
        return None

    def path_to_root(self, link_name: str) -> list[Joint]:
        """Chain of joints from `link_name` up to the root link."""
        chain = []
        current = link_name
        seen = set()
        while True:
            if current in seen:
                raise ValueError(f"Cycle detected in URDF kinematic tree at '{current}'")
            seen.add(current)
            pj = self.parent_joint_of(current)
            if pj is None:
                break
            chain.append(pj)
            current = pj.parent
        return list(reversed(chain))

    def static_transform(self, from_link: str, to_link: str) -> Optional[dict]:
        """
        Returns the composed fixed-joint-only transform between two links,
        as {'xyz': (...), 'rpy': (...)}. Only valid when every joint on the
        path is 'fixed' (i.e. a true static mount offset, like a sensor
        bracket) — for kinematic chains involving movable joints, callers
        need actual joint state, not just the URDF, so this returns None
        and the caller should use a live TF-style solver instead.
        """
        import numpy as np
        import math
        if from_link not in self.links or to_link not in self.links:
            raise ValueError("Unknown transform frame")
        path_a = self.path_to_root(from_link)
        path_b = self.path_to_root(to_link)
        root_a = path_a[0].parent if path_a else from_link
        root_b = path_b[0].parent if path_b else to_link
        if root_a != root_b:
            raise ValueError("Frames belong to disconnected trees")
        while path_a and path_b and path_a[0].name == path_b[0].name:
            path_a, path_b = path_a[1:], path_b[1:]
        joints_on_path = path_a + path_b
        for j in joints_on_path:
            if j.joint_type != "fixed":
                return None
        def compose(chain):
            result = np.eye(4)
            for joint in chain:
                result = result @ origin_matrix(joint.origin)
            return result
        matrix = np.linalg.inv(compose(path_a)) @ compose(path_b)
        pitch = math.asin(float(np.clip(-matrix[2, 0], -1, 1)))
        if abs(math.cos(pitch)) > 1e-8:
            roll, yaw = math.atan2(matrix[2, 1], matrix[2, 2]), math.atan2(matrix[1, 0], matrix[0, 0])
        else:
            roll, yaw = 0.0, math.atan2(-matrix[0, 1], matrix[1, 1])
        return {"xyz": tuple(matrix[:3, 3]), "rpy": (roll, pitch, yaw),
                "matrix": matrix.tolist(), "joints_used": [j.name for j in joints_on_path]}


def origin_matrix(origin: Origin):
    import math
    import numpy as np
    r, p, y = origin.rpy
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    matrix = np.eye(4)
    matrix[:3, :3] = [[cy*cp, cy*sp*sr-sy*cr, cy*sp*cr+sy*sr],
                       [sy*cp, sy*sp*sr+cy*cr, sy*sp*cr-cy*sr], [-sp, cp*sr, cp*cr]]
    matrix[:3, 3] = origin.xyz
    return matrix


def _parse_origin(elem: Optional[ET.Element]) -> Origin:
    if elem is None:
        return Origin()
    xyz_str = elem.get("xyz", "0 0 0")
    rpy_str = elem.get("rpy", "0 0 0")
    xyz = tuple(float(v) for v in xyz_str.split())
    rpy = tuple(float(v) for v in rpy_str.split())
    return Origin(xyz=xyz, rpy=rpy)  # type: ignore[arg-type]


def load_urdf(path: str | Path) -> RobotModel:
    """Parse a .urdf file into a RobotModel. For .xacro files, pre-process
    with the `xacro` CLI first (not invoked here — keep this function pure
    XML parsing; a `load_xacro()` wrapper can shell out to `xacro` and then
    call this)."""
    path = Path(path)
    return parse_urdf(path.read_text(encoding="utf-8"), path.stem)


def parse_urdf(xml: str, default_name: str = "robot") -> RobotModel:
    """Parse embedded URDF without writing temporary project files."""
    root = ET.fromstring(xml)
    if root.tag != "robot":
        raise ValueError(f"Not a URDF file (root tag is '{root.tag}', expected 'robot')")

    model = RobotModel(name=root.get("name", default_name))

    for link_elem in root.findall("link"):
        name = link_elem.get("name")
        visual = link_elem.find("visual/geometry/mesh")
        collision = link_elem.find("collision/geometry/mesh")
        inertial = link_elem.find("inertial/mass")
        geometry = link_elem.find("visual/geometry")
        shape = {}
        if geometry is not None and len(geometry):
            primitive = geometry[0]
            shape = {"type": primitive.tag, **dict(primitive.attrib)}
        color = link_elem.find("visual/material/color")
        model.links[name] = Link(
            name=name,
            visual_mesh=visual.get("filename") if visual is not None else None,
            collision_mesh=collision.get("filename") if collision is not None else None,
            inertial_mass=float(inertial.get("value")) if inertial is not None else None,
            visual_geometry=shape,
            visual_origin=_parse_origin(link_elem.find("visual/origin")),
            color=tuple(map(float, color.get("rgba").split())) if color is not None else (0.4, 0.5, 0.7, 1.0),
        )

    for joint_elem in root.findall("joint"):
        name = joint_elem.get("name")
        jtype = joint_elem.get("type")
        parent = joint_elem.find("parent").get("link")
        child = joint_elem.find("child").get("link")
        origin = _parse_origin(joint_elem.find("origin"))
        axis_elem = joint_elem.find("axis")
        axis = tuple(float(v) for v in axis_elem.get("xyz").split()) if axis_elem is not None else (0.0, 0.0, 1.0)
        limit_elem = joint_elem.find("limit")
        model.joints[name] = Joint(
            name=name,
            joint_type=jtype,
            parent=parent,
            child=child,
            origin=origin,
            axis=axis,  # type: ignore[arg-type]
            limit_lower=float(limit_elem.get("lower")) if limit_elem is not None and limit_elem.get("lower") else None,
            limit_upper=float(limit_elem.get("upper")) if limit_elem is not None and limit_elem.get("upper") else None,
            limit_effort=float(limit_elem.get("effort")) if limit_elem is not None and limit_elem.get("effort") else None,
            limit_velocity=float(limit_elem.get("velocity")) if limit_elem is not None and limit_elem.get("velocity") else None,
        )

    return model


def load_xacro(path: str | Path) -> RobotModel:
    """Pre-process a .xacro file into URDF XML via the `xacro` CLI, then parse it."""
    import subprocess
    import tempfile

    path = Path(path)
    with tempfile.NamedTemporaryFile(suffix=".urdf", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        result = subprocess.run(
            ["xacro", str(path), "-o", str(tmp_path)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"xacro processing failed for {path}:\n{result.stderr}")
        return load_urdf(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)
