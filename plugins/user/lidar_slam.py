from sdk.pyrobot_plugin import PluginManifest, PortSpec, PortDataType as T
from core.simulation.worker import WorkerNode
from core.simulation.navigation import LidarSlam


class LidarSlamNode(WorkerNode):
    manifest = PluginManifest(id="pyrobot.navigation.lidar_slam", name="Lidar SLAM (local)", category="Navigation",
        description="Encoder prediction + point-to-plane ICP scan-to-submap correction + occupancy mapping. No loop closure; never consumes simulator truth.",
        inputs=[PortSpec("observation", T.JSON, schema="pyrobot/Observation@1")], outputs=[PortSpec("state", T.JSON, schema="pyrobot/MappingState@1")])

    def on_start(self):
        mapping = self.robot_config.mapping
        self.slam = LidarSlam(resolution=mapping.resolution, origin=mapping.origin, size=(mapping.width, mapping.height))
        self.start_worker()

    def process(self, port, payload):
        self.slam.update(payload["odometry"], payload["scan"])
        self.emit("state", self.slam.state(payload["scan"], payload["time"]))
