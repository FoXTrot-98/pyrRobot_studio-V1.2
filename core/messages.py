"""Versioned robotics payload contracts. Distances: metres; angles: radians.

Legacy ports may omit a schema. A typed input only accepts the exact schema ID.
Defaults are materialized on publication; unknown fields and non-finite values
are rejected. Metadata describes payload coordinates, not the transport clock.
"""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator

Vec2 = Annotated[list[float], Field(min_length=2, max_length=2)]
Vec3 = Annotated[list[float], Field(min_length=3, max_length=3)]


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    schema_version: Literal[1] = 1
    frame: str = Field(min_length=1)

    @field_validator("frame")
    @classmethod
    def frame_required(cls, value):
        if not value.strip():
            raise ValueError("A nonempty coordinate frame is required")
        return value


class LaserScan(Message):
    frame: str = "lidar_link"
    length_unit: Literal["m"] = "m"
    angle_unit: Literal["rad"] = "rad"
    ranges: list[float] = Field(min_length=1, max_length=100000)
    angles: list[float]
    hits: list[bool]
    range_max: float = Field(gt=0)
    offset: Vec3

    @model_validator(mode="after")
    def consistent(self):
        if len(self.ranges) != len(self.angles) or len(self.ranges) != len(self.hits):
            raise ValueError("LaserScan ranges, angles and hits must have equal lengths")
        if any(r < 0 or r > self.range_max for r in self.ranges):
            raise ValueError("LaserScan range outside [0, range_max]")
        return self


class VelocityCommand(Message):
    frame: str = "base_link"
    linear_unit: Literal["m/s"] = "m/s"
    angular_unit: Literal["rad/s"] = "rad/s"
    linear: float
    angular: float
    time: float = Field(ge=0)


class Odometry(Message):
    frame: str = "odom"
    child_frame: str = "base_link"
    length_unit: Literal["m"] = "m"
    angle_unit: Literal["rad"] = "rad"
    pose: Vec3
    time: float = Field(ge=0)


class Image(Message):
    frame: str = "camera_link"
    encoding: Literal["jpeg"] = "jpeg"
    width: int = Field(gt=0, le=16384)
    height: int = Field(gt=0, le=16384)
    jpeg_base64: str = Field(min_length=1)
    time: float = Field(ge=0)
    source: str = "sensor"
    frame_link: str | None = None  # compatibility with the original camera plugin

    @model_validator(mode="after")
    def valid_image(self):
        import base64
        try:
            data = base64.b64decode(self.jpeg_base64, validate=True)
        except ValueError as exc:
            raise ValueError("Image contains invalid base64") from exc
        if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
            raise ValueError("Image must contain a JPEG payload")
        if self.frame_link is not None and self.frame_link != self.frame:
            raise ValueError("Image frame and legacy frame_link disagree")
        return self


class JointState(Message):
    frame: str = "base_link"
    angle_unit: Literal["rad"] = "rad"
    names: list[str]
    positions: list[float]
    time: float = Field(ge=0)

    @model_validator(mode="after")
    def consistent(self):
        if len(self.names) != len(self.positions) or len(set(self.names)) != len(self.names):
            raise ValueError("JointState requires unique names and one position per joint")
        return self


class OccupancyGrid(Message):
    frame: str = "map"
    length_unit: Literal["m"] = "m"
    grid: list[list[int]] = Field(min_length=1, max_length=2048)
    origin: Vec2
    resolution: float = Field(gt=0)
    time: float = Field(ge=0)

    @model_validator(mode="after")
    def consistent(self):
        width = len(self.grid[0])
        if not 0 < width <= 2048 or any(len(row) != width for row in self.grid):
            raise ValueError("OccupancyGrid must be rectangular, at most 2048 x 2048")
        if any(v < -1 or v > 100 for row in self.grid for v in row):
            raise ValueError("OccupancyGrid values must be -1 or 0..100")
        return self


class SensorPacket(Message):
    frame: str = "base_link"
    length_unit: Literal["m"] = "m"
    encoder_unit: Literal["tick"] = "tick"
    ticks: Annotated[list[int], Field(min_length=4, max_length=4)]
    wheel_radius: float = Field(gt=0)
    track: float = Field(gt=0)
    ticks_per_turn: int = Field(gt=0)
    scan: LaserScan
    time: float = Field(ge=0)


class Observation(Message):
    frame: str = "odom"
    length_unit: Literal["m"] = "m"
    angle_unit: Literal["rad"] = "rad"
    odometry: Vec3
    scan: LaserScan
    time: float = Field(ge=0)


class MappingState(OccupancyGrid):
    pose: Vec3
    scan: LaserScan
    mapped_cells: int = Field(ge=0)
    algorithm: str


class NavigationPath(Message):
    frame: str = "map"
    length_unit: Literal["m"] = "m"
    angle_unit: Literal["rad"] = "rad"
    points: list[Vec2]
    goal: Vec2
    pose: Vec3 | None
    status: Literal["navigating", "no_path", "goal_reached", "obstacle_stop", "paused", "sensor_timeout", "mission_complete", "replanning", "stalled", "navigation_failed", "returning_home", "aligning_home", "home_reached", "cancelled"]
    planner: Literal["astar", "dijkstra"] = "astar"
    controller: Literal["proportional", "fuzzy"] = "proportional"
    mission_id: str = ""
    mission_type: Literal["goal", "waypoints", "exploration", "return_home"] = "goal"
    mission_state: Literal["running", "paused", "recovering", "waiting_for_sensors", "completed", "failed", "cancelled"] = "running"
    recovery_action: Literal["none", "start_new", "retry_or_cancel", "resume_or_cancel", "wait_for_sensors", "automatic_replan"] = "none"
    home_pose: Vec3 | None = None
    returning_home: bool = False
    exploring: bool = False
    exploration_targets: int = Field(default=0, ge=0)
    reason: str | None = Field(default=None, max_length=500)
    replans: int = Field(default=0, ge=0)
    waypoints: list[Vec2] = Field(default_factory=list)
    waypoint_index: int = Field(default=0, ge=0)
    distance_to_goal: float | None = Field(default=None, ge=0)
    time: float = Field(ge=0)


class JointTargets(Message):
    frame: str = "robot"
    # Device-native SI positions: radians for rotational joints, metres for linear joints.
    # Names and position limits are checked against actual Webots devices.
    positions: dict[str, float] = Field(min_length=1, max_length=128)


class JointReading(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: str
    position: float
    unit: Literal["rad", "m"]


class WebotsRobotState(Message):
    frame: str = "world"
    profile: str
    time: float = Field(ge=0)
    position: Vec3
    joints: list[JointReading]
    status: str
    error: str = ""


SCHEMAS = {f"pyrobot/{cls.__name__}@1": cls for cls in (
    LaserScan, VelocityCommand, Odometry, Image, JointState, OccupancyGrid,
    SensorPacket, Observation, MappingState, NavigationPath, JointTargets, WebotsRobotState)}


def validate_payload(schema, payload):
    if schema is None:
        return payload
    if schema not in SCHEMAS:
        raise ValueError(f"Unknown message schema: {schema}")
    return SCHEMAS[schema].model_validate(payload).model_dump()
