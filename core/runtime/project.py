"""Version 2 project documents, accepting version 1 with configuration defaults.

URDF XML is embedded. Meshes, model weights and plugin source are external
dependencies in v1, not silently claimed to be bundled.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
    schema_version: Literal[1, 2] = 2
    name: str = Field(default="Untitled robot", min_length=1, max_length=200)
    robot_urdf: str | None = None
    nodes: list[ProjectNode] = Field(default_factory=list)
    connections: list[ProjectConnection] = Field(default_factory=list)
    positions: dict[str, Position] = Field(default_factory=dict)
    robot_config: RobotConfiguration = Field(default_factory=RobotConfiguration)


def prepare_project(document: ProjectDocument, bus, registry):
    """Create a stopped candidate; dispose all subscriptions on failure."""
    candidate = NodeGraph(bus, registry)
    try:
        robot = parse_urdf(document.robot_urdf) if document.robot_urdf else None
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
        name=name, robot_urdf=robot_urdf, positions=positions,
        robot_config=graph.robot_config,
        nodes=[ProjectNode(
            node_id=n["node_id"], plugin_id=n["plugin_id"], params=n["params"],
            urdf_link=n["urdf_link"],
            plugin_version=registry.get(n["plugin_id"]).manifest.version,
        ) for n in state["nodes"]],
        connections=state["connections"],
    )
