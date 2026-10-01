# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""
Plugin manifest — the introspectable description of a node that lets the
Studio UI auto-generate node cards, ports, and parameter forms WITHOUT any
frontend code needing to know about a specific plugin ahead of time.

A plugin author writes a plugin.toml (or declares this in Python — both
supported) and the manifest gets served to the frontend via the backend's
/api/plugins endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class PortDataType(Enum):
    IMAGE = "image"
    POINTCLOUD = "pointcloud"
    POSE = "pose"
    IMU = "imu"
    STRING = "string"
    NUMBER = "number"
    BOOL = "bool"
    JSON = "json"
    ANY = "any"


@dataclass
class PortSpec:
    name: str
    data_type: PortDataType
    required: bool = True
    description: str = ""
    schema: Optional[str] = None


@dataclass
class ParamSpec:
    """A user-configurable parameter shown in the node's property panel."""
    name: str
    kind: str  # "number" | "string" | "bool" | "enum" | "file"
    default: Any = None
    min: Optional[float] = None
    max: Optional[float] = None
    options: Optional[list[str]] = None  # for kind="enum"
    description: str = ""


@dataclass
class PluginManifest:
    id: str                     # unique, e.g. "pyrobot.builtin.camera_source"
    name: str                   # display name, e.g. "Camera Source"
    category: str               # groups nodes in the UI palette, e.g. "Sensors"
    version: str = "0.1.0"
    author: str = ""
    description: str = ""
    icon: Optional[str] = None  # icon identifier for the UI
    inputs: list[PortSpec] = field(default_factory=list)
    outputs: list[PortSpec] = field(default_factory=list)
    params: list[ParamSpec] = field(default_factory=list)
    requires_urdf_link: bool = False  # if true, node can bind to a URDF link/frame

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "icon": self.icon,
            "inputs": [
                {"name": p.name, "data_type": p.data_type.value, "required": p.required, "description": p.description, "schema": p.schema}
                for p in self.inputs
            ],
            "outputs": [
                {"name": p.name, "data_type": p.data_type.value, "required": p.required, "description": p.description, "schema": p.schema}
                for p in self.outputs
            ],
            "params": [
                {
                    "name": p.name, "kind": p.kind, "default": p.default,
                    "min": p.min, "max": p.max, "options": p.options,
                    "description": p.description,
                }
                for p in self.params
            ],
            "requires_urdf_link": self.requires_urdf_link,
        }
