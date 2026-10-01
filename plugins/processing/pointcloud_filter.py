# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""
Point Cloud Filter — a real processing node: voxel-grid downsampling.
"""

import numpy as np

from sdk.pyrobot_plugin import Node, PluginManifest, PortSpec, PortDataType, ParamSpec


def voxel_downsample(points: np.ndarray, voxel_size: float) -> np.ndarray:
    """Keep one point (the centroid) per occupied voxel cell."""
    if len(points) == 0:
        return points
    voxel_indices = np.floor(points / voxel_size).astype(np.int64)
    _, inverse, counts = np.unique(voxel_indices, axis=0, return_inverse=True, return_counts=True)
    sums = np.zeros((len(counts), 3), dtype=np.float64)
    np.add.at(sums, inverse, points)
    centroids = sums / counts[:, None]
    return centroids


class PointCloudFilterNode(Node):
    manifest = PluginManifest(
        id="pyrobot.processing.pointcloud_filter",
        name="Point Cloud Filter",
        category="Processing",
        description="Voxel-grid downsamples an incoming point cloud to reduce density before downstream processing.",
        inputs=[PortSpec("points_in", PortDataType.POINTCLOUD)],
        outputs=[PortSpec("points_out", PortDataType.POINTCLOUD)],
        params=[
            ParamSpec(name="voxel_size", kind="number", default=0.05, min=0.001, max=2.0, description="Voxel edge length in meters"),
        ],
    )

    def on_message(self, port: str, message) -> None:
        if port != "points_in":
            return
        points = np.asarray(message.payload.get("points", []), dtype=np.float64)
        voxel_size = self.get_param("voxel_size", 0.05)
        filtered = voxel_downsample(points, voxel_size)
        self.emit("points_out", {
            "points": filtered.tolist(),
            "input_count": int(len(points)),
            "output_count": int(len(filtered)),
            "voxel_size": voxel_size,
        })
