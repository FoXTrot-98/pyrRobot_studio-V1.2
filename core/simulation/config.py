"""Portable reference-simulator configuration stored in the project document."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class DriveSettings(Settings):
    type: Literal["four_wheel_differential"] = "four_wheel_differential"
    base_frame: str = "base_link"
    left_joints: Annotated[list[str], Field(min_length=2, max_length=2)] = ["front_left_wheel_joint", "rear_left_wheel_joint"]
    right_joints: Annotated[list[str], Field(min_length=2, max_length=2)] = ["front_right_wheel_joint", "rear_right_wheel_joint"]
    lidar_frame: str = "lidar_link"
    camera_frame: str = "camera_link"
    wheel_radius: float | None = Field(default=None, gt=0)
    collision_radius: float = Field(default=.48, gt=0, le=5)
    ticks_per_turn: int = Field(default=4096, gt=0)

    @model_validator(mode="after")
    def unique_joints(self):
        if len(set(self.left_joints + self.right_joints)) != 4:
            raise ValueError("Select four distinct wheel joints")
        return self


class EnvironmentSettings(Settings):
    bounds: Annotated[list[float], Field(min_length=4, max_length=4)] = [-2, -2, 10, 8]
    obstacles: list[Annotated[list[float], Field(min_length=5, max_length=5)]] = [
        [2,-1,2.8,3.5,1], [5,3,6,6.5,1.3], [0,5,2,6,.9], [7.5,0,8.5,1.8,1.1]]

    @model_validator(mode="after")
    def ordered_boxes(self):
        x0, y0, x1, y1 = self.bounds
        if not x0 < 0 < x1 or not y0 < 0 < y1:
            raise ValueError("Room bounds must contain the starting position (0, 0)")
        for a,b,c,d,h in self.obstacles:
            if not (x0 <= a < c <= x1 and y0 <= b < d <= y1 and h > 0):
                raise ValueError("Obstacles need ordered corners inside room bounds and positive height")
        return self

    def boxes(self):
        a,b,c,d = self.bounds
        return [[a-.2,b-.2,c+.2,b,1.6], [a-.2,d,c+.2,d+.2,1.6],
                [a-.2,b,a,d,1.6], [c,b,c+.2,d,1.6]] + self.obstacles


class MapSettings(Settings):
    origin: Annotated[list[float], Field(min_length=2, max_length=2)] = [-2.4, -2.4]
    width: int = Field(default=108, gt=0, le=512)
    height: int = Field(default=91, gt=0, le=512)
    resolution: float = Field(default=.12, gt=0, le=2)
    inflation_radius: float = Field(default=.65, gt=0, le=10)


class RobotConfiguration(Settings):
    drive: DriveSettings = Field(default_factory=DriveSettings)
    environment: EnvironmentSettings = Field(default_factory=EnvironmentSettings)
    mapping: MapSettings = Field(default_factory=MapSettings)

    @model_validator(mode="after")
    def consistent(self):
        m, d = self.mapping, self.drive
        if m.inflation_radius < d.collision_radius:
            raise ValueError("Map inflation must cover the configured robot collision radius")
        a,b,c,e = self.environment.bounds
        if m.origin[0] > a or m.origin[1] > b or m.origin[0]+m.width*m.resolution < c or m.origin[1]+m.height*m.resolution < e:
            raise ValueError("Occupancy map must cover the configured room")
        return self
