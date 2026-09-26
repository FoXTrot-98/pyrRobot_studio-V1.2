"""Version 1/2 projects plus version 3 embedded Model Builder mesh assets.

Plugin source, arbitrary external files and dependencies remain separate.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from core.urdf.assets import Assets, attach_assets, validate_assets

from core.urdf.model import parse_urdf
from .graph import NodeGraph, GraphError
from core.simulation.config import RobotConfiguration


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
    schema_version: Literal[1, 2, 3] = 2
    name: str = Field(default="Untitled robot", min_length=1, max_length=200)
    robot_urdf: str | None = None
    nodes: list[ProjectNode] = Field(default_factory=list)
    connections: list[ProjectConnection] = Field(default_factory=list)
    positions: dict[str, Position] = Field(default_factory=dict)
    robot_config: RobotConfiguration = Field(default_factory=RobotConfiguration)
    robot_assets: Assets = Field(default_factory=dict)

    @model_validator(mode='after')
    def assets_valid(self):
        validate_assets(self.robot_assets)
        if self.robot_assets and (self.schema_version != 3 or not self.robot_urdf):
            raise ValueError('Embedded robot meshes require a version 3 project with URDF')
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
    return ProjectDocument(
        schema_version=3 if graph.robot_model and graph.robot_model.assets else 2,
        robot_assets=graph.robot_model.assets if graph.robot_model else {},
        name=name, robot_urdf=robot_urdf, positions=positions,
        robot_config=graph.robot_config,
        nodes=[ProjectNode(
            node_id=n["node_id"], plugin_id=n["plugin_id"], params=n["params"],
            urdf_link=n["urdf_link"],
            plugin_version=registry.get(n["plugin_id"]).manifest.version,
        ) for n in state["nodes"]],
        connections=state["connections"],
    )
