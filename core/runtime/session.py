# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Own runtime resources independently of any HTTP server or UI."""
from pathlib import Path
import threading

from core.bus.base import Bus, ZmqTransport
from core.bus.broker import run_broker, FRONTEND_ENDPOINT, BACKEND_ENDPOINT
from core.timing.clock import PRTClock, ClockAuthority, discipline_from_beacon
from core.urdf.model import parse_urdf
from .graph import NodeGraph, GraphError
from .plugin_registry import PluginRegistry
from .project import ProjectDocument, prepare_project, export_project


PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins"
DEFAULT_PLUGIN_DIRS = tuple(PLUGIN_ROOT / name for name in ("examples", "devices", "processing", "user"))


class Runtime:
    """One session, broker, bus and graph. No FastAPI dependency.

    A runtime owns its broker endpoints; use different endpoints for multiple
    concurrent runtimes. Opening a project never starts its devices.
    """

    def __init__(self, plugin_dirs=DEFAULT_PLUGIN_DIRS, pub_endpoint=FRONTEND_ENDPOINT,
                 sub_endpoint=BACKEND_ENDPOINT):
        self.lock = threading.RLock()
        self.plugin_dirs = tuple(Path(p) for p in plugin_dirs)
        self.pub_endpoint, self.sub_endpoint = pub_endpoint, sub_endpoint
        self.registry = PluginRegistry()
        self.bus = None
        self.graph = None
        self.robot = None
        self.robot_xml = None
        self.name = "Untitled robot"
        self.positions = {}
        self._broker_stop = threading.Event()
        self._broker_thread = None

    def open(self):
        with self.lock:
            if self.bus is not None:
                return self
            self.registry = PluginRegistry()
            for directory in self.plugin_dirs:
                self.registry.scan_directory(directory)
            self._broker_stop.clear()
            ready, errors = threading.Event(), []
            self._broker_thread = threading.Thread(target=run_broker, kwargs={
                "frontend": self.pub_endpoint, "backend": self.sub_endpoint,
                "stop_event": self._broker_stop, "ready_event": ready, "errors": errors,
            }, name="pyrobot-broker", daemon=True)
            self._broker_thread.start()
            try:
                if not ready.wait(5) or errors:
                    raise RuntimeError(f"Could not start message broker: {errors}")
                authority = ClockAuthority(lambda topic, payload: None)
                authority.start_session()
                clock = PRTClock(source_id="runtime")
                discipline_from_beacon(clock, authority.emit_beacon())
                self.bus = Bus(ZmqTransport(self.pub_endpoint, self.sub_endpoint), clock)
                self.graph = NodeGraph(self.bus, self.registry)
                self.robot = self.robot_xml = None
                self.name, self.positions = "Untitled robot", {}
            except Exception:
                self.close()
                raise
            return self

    def close(self):
        with self.lock:
            try:
                if self.graph is not None:
                    self.graph.close()
            finally:
                if self.bus is not None:
                    self.bus.close()
                self._broker_stop.set()
                if self._broker_thread:
                    self._broker_thread.join(timeout=5)
                self.bus = self.graph = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()

    def robot_info(self):
        with self.lock:
            if self.robot is None:
                return None
            return {"name": self.robot.name, "links": self.robot.link_names(),
                    "joint_count": len(self.robot.joints)}

    def project_info(self):
        with self.lock:
            return {"name": self.name, "positions": {k: dict(v) for k, v in self.positions.items()},
                    "robot": self.robot_info(), "robot_config": self.graph.robot_config.model_dump()}

    def set_robot_config(self, configuration):
        with self.lock:
            if self.graph.to_dict()["running"]:
                raise GraphError("Stop the graph before changing robot configuration")
            previous = self.graph.robot_config
            self.graph.robot_config = configuration
            try:
                for instance in self.graph.nodes.values():
                    instance.node_obj.robot_config = configuration
                    instance.node_obj.validate_configuration()
            except Exception:
                self.graph.robot_config = previous
                for instance in self.graph.nodes.values():
                    instance.node_obj.robot_config = previous
                raise
            return self.project_info()

    def set_robot(self, xml):
        model = parse_urdf(xml)
        with self.lock:
            if self.graph.to_dict()["running"]:
                raise GraphError("Stop the graph before changing the robot")
            for instance in self.graph.nodes.values():
                if instance.urdf_link and instance.urdf_link not in model.links:
                    raise GraphError(f"New robot is missing bound link '{instance.urdf_link}'")
            self.robot, self.robot_xml = model, xml
            self.graph.robot_model = model
            for instance in self.graph.nodes.values():
                instance.node_obj.robot_model = model
            return self.robot_info()

    def add_node(self, node_id, plugin_id, params=None, urdf_link=None):
        with self.lock:
            if urdf_link and (self.robot is None or urdf_link not in self.robot.links):
                raise GraphError("Upload a robot and select one of its links")
            return self.graph.add_node(node_id, plugin_id, params, urdf_link)

    def remove_node(self, node_id):
        with self.lock:
            self.graph.remove_node(node_id)
            self.positions.pop(node_id, None)

    def bind_node(self, node_id, link):
        with self.lock:
            if self.graph.to_dict()["running"]:
                raise GraphError("Stop the graph before changing a device binding")
            if node_id not in self.graph.nodes:
                raise GraphError("Unknown node")
            if self.robot is None or link not in self.robot.links:
                raise GraphError("Unknown robot link")
            instance = self.graph.nodes[node_id]
            instance.urdf_link = instance.node_obj.urdf_link = link

    def load_project(self, document: ProjectDocument):
        with self.lock:
            if self.graph is None:
                raise GraphError("Open the runtime before loading a project")
            if self.graph.to_dict()["running"]:
                raise GraphError("Stop the graph before opening another project")
            candidate, robot = prepare_project(document, self.bus, self.registry)
            try:
                self.graph.close()
            except Exception:
                candidate.close()
                raise
            self.graph = candidate
            self.robot, self.robot_xml = robot, document.robot_urdf
            self.name = document.name
            self.positions = {k: v.model_dump() for k, v in document.positions.items()}
            return self.project_info()

    def _mapping_node(self, nav_id):
        nav=self.graph.nodes.get(nav_id)
        if nav is None or nav.plugin_id != "pyrobot.navigation.astar":
            raise GraphError("Select a navigation node")
        connections=[c for c in self.graph.connections.values() if c.to_node==nav_id and c.to_port=="state"]
        if len(connections)!=1:
            raise GraphError("Connect a SLAM map to navigation first")
        source=self.graph.nodes[connections[0].from_node]
        if source.plugin_id != "pyrobot.navigation.lidar_slam":
            raise GraphError("Map snapshots require the local lidar SLAM node")
        return source.node_obj

    def map_info(self, nav_id):
        with self.lock:
            node=self._mapping_node(nav_id)
            return {"snapshot":node.saved_map.model_dump(mode="json") if node.saved_map else None,
                    "start_pose":node.map_start_pose,
                    "can_capture":node._latest_state is not None}

    def capture_map(self, nav_id, name):
        with self.lock:
            node=self._mapping_node(nav_id)
            homes={}
            for c in self.graph.connections.values():
                if c.from_node==node.node_id and c.to_port=="state":
                    target=self.graph.nodes[c.to_node]
                    if target.plugin_id=="pyrobot.navigation.astar":
                        with target.node_obj._control_lock:
                            if target.node_obj._home_pose is not None:
                                homes[c.to_node]=list(target.node_obj._home_pose)
            node.saved_map=node.snapshot(name,homes)
            node.map_start_pose=None
            return self.map_info(nav_id)

    def initialize_map(self, nav_id, pose):
        import math
        with self.lock:
            if self.graph.to_dict()["running"]:
                raise GraphError("Stop the graph before initializing a saved map")
            node=self._mapping_node(nav_id)
            snapshot=node.saved_map
            if snapshot is None:
                raise GraphError("Capture or open a saved map first")
            snapshot.check_config(self.graph.robot_config)
            if len(pose)!=3 or not all(math.isfinite(v) for v in pose):
                raise GraphError("Starting pose must contain three finite coordinates")
            x,y=[math.floor((pose[i]-snapshot.origin[i])/snapshot.resolution) for i in (0,1)]
            if not (0 <= y < len(snapshot.grid) and 0 <= x < len(snapshot.grid[0]) and snapshot.grid[y][x]==0):
                raise GraphError("Starting pose must be in measured free space")
            from core.simulation.navigation import plan_path
            if not plan_path(snapshot.grid,snapshot.origin,snapshot.resolution,pose,pose[:2],radius=self.graph.robot_config.mapping.inflation_radius):
                raise GraphError("Starting pose is too close to mapped obstacles")
            node.map_start_pose=list(pose)
            return self.map_info(nav_id)

    def clear_map(self, nav_id):
        with self.lock:
            if self.graph.to_dict()["running"]:
                raise GraphError("Stop the graph before removing a saved map")
            node=self._mapping_node(nav_id)
            node.saved_map=None
            node.map_start_pose=None
            node._latest_state=None
            for c in self.graph.connections.values():
                if c.from_node==node.node_id and c.to_port=="state" and self.graph.nodes[c.to_node].plugin_id=="pyrobot.navigation.astar":
                    self.graph.update_node_params(c.to_node,{"home_pose":[],"enabled":False})
            return self.map_info(nav_id)

    def export(self, name=None, positions=None):
        with self.lock:
            positions = self.positions if positions is None else positions
            if set(positions) - self.graph.nodes.keys():
                raise GraphError("Layout references unknown nodes")
            document = export_project(self.graph, self.registry, name or self.name,
                                      self.robot_xml, positions)
            self.name = document.name
            self.positions = {k: v.model_dump() for k, v in document.positions.items()}
            return document
