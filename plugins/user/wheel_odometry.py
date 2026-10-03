# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

from sdk.pyrobot_plugin import PluginManifest, PortSpec, PortDataType as T
from core.simulation.worker import WorkerNode
from core.simulation.navigation import WheelOdometry


class EncoderOdometry(WorkerNode):
    manifest = PluginManifest(id="pyrobot.navigation.wheel_odometry", name="Wheel encoder odometry",
        category="Navigation", description="Integrates wheel encoders and optional accumulated gyro heading; passes the synchronized lidar scan onward.",
        inputs=[PortSpec("sensors", T.JSON, schema="pyrobot/SensorPacket@1")], outputs=[PortSpec("observation", T.JSON, schema="pyrobot/Observation@1")])

    def on_start(self):
        self.odometry = WheelOdometry()
        self.start_worker()

    def process(self, port, payload):
        pose = self.odometry.update(payload["ticks"], payload["wheel_radius"], payload["track"], payload["ticks_per_turn"], payload.get("gyro_yaw"))
        self.emit("observation", {"odometry": pose.tolist(), "gyro_yaw": self.odometry.relative_gyro(payload.get("gyro_yaw")), "scan": payload["scan"], "time": payload["time"]})
