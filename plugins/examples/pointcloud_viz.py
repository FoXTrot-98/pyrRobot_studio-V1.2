"""
Example plugin: a stand-in for a real SLAM node. Generates a synthetic
point cloud that drifts over time and a trajectory pose, logging both to
Rerun so there's something real to look at in the 3D viewport before any
actual SLAM algorithm (fast-lio, etc.) is wired in.
"""

import math
import threading
import time

import numpy as np
import rerun as rr

from sdk.pyrobot_plugin import Node, PluginManifest, PortSpec, PortDataType, ParamSpec


class PointCloudVizNode(Node):
    manifest = PluginManifest(
        id="pyrobot.examples.pointcloud_viz",
        name="SLAM (Rerun)",
        category="Processing",
        description="Synthetic SLAM stand-in: logs a drifting point cloud and trajectory to the Rerun 3D viewport.",
        outputs=[PortSpec("pose", PortDataType.POSE)],
        params=[
            ParamSpec(name="rate_hz", kind="number", default=10, min=1, max=60),
            ParamSpec(name="point_count", kind="number", default=400, min=50, max=5000),
        ],
    )

    def on_start(self) -> None:
        self._stop = threading.Event()
        self._t = 0.0
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def on_stop(self) -> None:
        self._stop.set()

    def on_params_changed(self, updated: dict) -> None:
        if "rate_hz" in updated or "point_count" in updated:
            self._stop.set()
            self._thread.join(timeout=1.0)
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def _run(self) -> None:
        rate_hz = self.get_param("rate_hz", 10)
        n_points = int(self.get_param("point_count", 400))
        period = 1.0 / rate_hz

        rng = np.random.default_rng(42)
        room = rng.uniform(-3, 3, size=(n_points, 3))
        room[:, 2] = np.abs(room[:, 2]) * 0.3

        trajectory: list[list[float]] = []
        max_trail_length = 300

        while not self._stop.is_set():
            self._t += period
            radius = 1.5
            x = radius * math.cos(self._t * 0.4)
            y = radius * math.sin(self._t * 0.4)
            z = 0.0

            trajectory.append([x, y, z])
            if len(trajectory) > max_trail_length:
                trajectory.pop(0)

            rr.log("world/room_points", rr.Points3D(room, colors=[150, 160, 175], radii=0.02))
            rr.log("world/robot", rr.Transform3D(translation=[x, y, z]))
            rr.log("world/robot/marker", rr.Points3D([[0, 0, 0]], colors=[62, 99, 221], radii=0.08))
            rr.log(
                "world/robot_trajectory",
                rr.Points3D(np.array(trajectory), colors=[22, 163, 74], radii=0.015),
            )

            self.emit("pose", {"x": x, "y": y, "z": z, "t": self._t})
            self._stop.wait(period)
