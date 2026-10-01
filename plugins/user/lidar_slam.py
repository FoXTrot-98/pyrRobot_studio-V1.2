# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

import threading
import numpy as np
from core.simulation.saved_map import SavedMap
from sdk.pyrobot_plugin import PluginManifest, PortSpec, PortDataType as T
from core.simulation.worker import WorkerNode
from core.simulation.navigation import LidarSlam


class LidarSlamNode(WorkerNode):
    manifest = PluginManifest(id="pyrobot.navigation.lidar_slam", name="Lidar SLAM (local)", category="Navigation",
        description="Wheel/optional gyro prediction + scan-to-submap correction + occupancy mapping. No loop closure; never consumes simulator truth.",
        inputs=[PortSpec("observation", T.JSON, schema="pyrobot/Observation@1")], outputs=[PortSpec("state", T.JSON, schema="pyrobot/MappingState@1")])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._map_lock = threading.RLock()
        self.saved_map = None
        self.map_start_pose = None
        self._latest_state = None

    def validate_configuration(self):
        if self.saved_map:
            self.saved_map.check_config(self.robot_config)

    def on_start(self):
        self.validate_configuration()
        if self.saved_map and self.map_start_pose is None:
            raise ValueError("Saved map requires an explicit starting pose. Confirm it in Maps, or remove the saved map.")
        mapping = self.robot_config.mapping
        self.slam = LidarSlam(resolution=mapping.resolution, origin=mapping.origin, size=(mapping.width, mapping.height))
        self.slam.pose = np.asarray(self.robot_config.spawn_pose, dtype=float).copy()
        if self.saved_map:
            values=np.asarray(self.saved_map.grid)
            self.slam.grid[:]=np.where(values<0,0.,np.where(values>=50,4.,-4.))
            self.slam.pose=np.array(self.map_start_pose,dtype=float)
        self._latest_state=None
        self.start_worker()

    def process(self, port, payload):
        with self._map_lock:
            self.slam.update(payload["odometry"], payload["scan"], payload.get("gyro_yaw"))
            state=self.slam.state(payload["scan"], payload["time"])
            self._latest_state=state
        self.emit("state", state)

    def snapshot(self, name, home_poses):
        with self._map_lock:
            state=self._latest_state
            if state is None or not state["mapped_cells"]:
                raise ValueError("Wait for a measured map before saving a snapshot")
            return SavedMap(name=name,grid=state["grid"],origin=state["origin"],resolution=state["resolution"],
                captured_pose=state["pose"],home_poses=home_poses,
                webots_world_hash=self.robot_config.webots_world_hash, environment=self.robot_config.environment.model_dump(mode="json"))

    def on_stop(self):
        super().on_stop()
        self.map_start_pose=None
