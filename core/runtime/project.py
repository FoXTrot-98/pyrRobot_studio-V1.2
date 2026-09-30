"""Version 1/2 projects, version 3 mesh assets and version 4 map snapshots.

Plugin source, arbitrary external files and dependencies remain separate.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from core.urdf.assets import Assets, attach_assets, validate_assets

from core.urdf.model import parse_urdf
from .graph import NodeGraph, GraphError
from core.simulation.config import RobotConfiguration
from core.simulation.saved_map import SavedMap


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Position(StrictModel):
    x: float
    y: float


class ProjectNode(StrictModel):
    node_id: str
    plugin_id: str
    plugin_version: str
    params: dict = Field(default_factory=dict)
    urdf_link: str | None = None


class ProjectConnection(StrictModel):
    from_node: str
    from_port: str
    to_node: str
    to_port: str


class ProjectDocument(StrictModel):
    format: Literal["pyrobot-project"] = "pyrobot-project"
    schema_version: Literal[1, 2, 3, 4] = 2
    name: str = Field(default="Untitled robot", min_length=1, max_length=200)
    robot_urdf: str | None = None
    nodes: list[ProjectNode] = Field(default_factory=list)
    connections: list[ProjectConnection] = Field(default_factory=list)
    positions: dict[str, Position] = Field(default_factory=dict)
    robot_config: RobotConfiguration = Field(default_factory=RobotConfiguration)
    robot_assets: Assets = Field(default_factory=dict)
    saved_maps: dict[str,SavedMap] = Field(default_factory=dict,max_length=16)

    @model_validator(mode='after')
    def assets_valid(self):
        validate_assets(self.robot_assets)
        if self.robot_assets and (self.schema_version < 3 or not self.robot_urdf):
            raise ValueError('Embedded robot meshes require a version 3 or newer project with URDF')
        if self.saved_maps and self.schema_version != 4:
            raise ValueError("Saved maps require a version 4 project")
        for node_id, snapshot in self.saved_maps.items():
            if not any(n.node_id==node_id and n.plugin_id=="pyrobot.navigation.lidar_slam" for n in self.nodes):
                raise ValueError("Saved map must reference a SLAM node")
            snapshot.check_config(self.robot_config)
            for nav_id in snapshot.home_poses:
                if not any(n.node_id==nav_id and n.plugin_id=="pyrobot.navigation.astar" for n in self.nodes):
                    raise ValueError("Saved home must reference a navigation node")
                if not any(c.from_node==node_id and c.to_node==nav_id and c.to_port=="state" for c in self.connections):
                    raise ValueError("Saved home must use this map's navigation connection")
        return self


def prepare_project(document: ProjectDocument, bus, registry):
    """Create a stopped candidate; dispose all subscriptions on failure."""
    candidate = NodeGraph(bus, registry)
    try:
        robot = parse_urdf(document.robot_urdf) if document.robot_urdf else None
        if robot: attach_assets(robot, document.robot_assets)
        candidate.robot_model = robot
        candidate.robot_config = document.robot_config
        for node in document.nodes:
            entry = registry.get(node.plugin_id)
            if node.plugin_version != entry.manifest.version:
                raise GraphError(f"Plugin {node.plugin_id} requires version {node.plugin_version}; installed: {entry.manifest.version}")
            if node.urdf_link and (robot is None or node.urdf_link not in robot.links):
                raise GraphError(f"Unknown robot link '{node.urdf_link}' for {node.node_id}")
            candidate.add_node(node.node_id, node.plugin_id, node.params, node.urdf_link)
        for node_id,snapshot in document.saved_maps.items():
            candidate.nodes[node_id].node_obj.saved_map=snapshot.model_copy(deep=True)
            for nav_id,home in snapshot.home_poses.items():
                if not candidate.nodes[nav_id].node_obj.get_param("home_pose",[]):
                    candidate.update_node_params(nav_id,{"home_pose":list(home)})
        for connection in document.connections:
            candidate.connect(**connection.model_dump())
        if set(document.positions) - candidate.nodes.keys():
            raise GraphError("Project layout references unknown nodes")
        return candidate, robot
    except Exception:
        candidate.close()
        raise


def export_project(graph, registry, name, robot_urdf, positions):
    state = graph.to_dict()
    saved_maps={n.node_id:n.node_obj.saved_map for n in graph.nodes.values()
                if n.plugin_id=="pyrobot.navigation.lidar_slam" and n.node_obj.saved_map is not None}
    for node_id,snapshot in list(saved_maps.items()):
        connected={c.to_node for c in graph.connections.values() if c.from_node==node_id and c.to_port=="state"}
        saved_maps[node_id]=snapshot.model_copy(update={"home_poses":{key:pose for key,pose in snapshot.home_poses.items() if key in connected and key in graph.nodes}})
    # A snapshot includes the session-captured home without changing a live mission.
    homes={key:list(pose) for snapshot in saved_maps.values() for key,pose in snapshot.home_poses.items()}
    return ProjectDocument(
        schema_version=4 if saved_maps else 3 if graph.robot_model and graph.robot_model.assets else 2,
        saved_maps=saved_maps,
        robot_assets=graph.robot_model.assets if graph.robot_model else {},
        name=name, robot_urdf=robot_urdf, positions=positions,
        robot_config=graph.robot_config,
        nodes=[ProjectNode(
            node_id=n["node_id"], plugin_id=n["plugin_id"], params={**n["params"], **({"home_pose":homes[n["node_id"]]} if n["node_id"] in homes and not n["params"].get("home_pose") else {})},
            urdf_link=n["urdf_link"],
            plugin_version=registry.get(n["plugin_id"]).manifest.version,
        ) for n in state["nodes"]],
        connections=state["connections"],
    )
