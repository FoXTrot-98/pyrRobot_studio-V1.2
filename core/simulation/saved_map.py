# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Portable occupancy snapshots; operator pose initialization is not localization."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

class SavedMap(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: str = Field(default="Saved map", min_length=1, max_length=100)
    frame: Literal["map"] = "map"
    resolution: float = Field(gt=0, le=10)
    origin: tuple[float,float]
    grid: list[list[StrictInt]] = Field(min_length=1,max_length=512)
    captured_pose: tuple[float,float,float]
    home_poses: dict[str,tuple[float,float,float]] = Field(default_factory=dict,max_length=32)
    webots_world_hash: str = ""
    environment: dict

    @model_validator(mode="after")
    def rectangular(self):
        width=len(self.grid[0])
        if not 1 <= width <= 512 or any(len(row)!=width or any(v not in (-1,0,100) for v in row) for row in self.grid):
            raise ValueError("Saved occupancy must be rectangular, at most 512x512, with -1/0/100 cells")
        for home in self.home_poses.values():
            if not (self.origin[0] <= home[0] < self.origin[0]+width*self.resolution and self.origin[1] <= home[1] < self.origin[1]+len(self.grid)*self.resolution):
                raise ValueError("Saved home is outside the occupancy map")
        return self

    def check_config(self, config):
        m=config.mapping
        if (self.webots_world_hash!=config.webots_world_hash or self.resolution!=m.resolution or list(self.origin)!=list(m.origin) or
            len(self.grid)!=m.height or len(self.grid[0])!=m.width or self.environment!=config.environment.model_dump(mode="json")):
            raise ValueError("Saved map does not match map geometry/environment. Remove the saved map before changing these settings.")
