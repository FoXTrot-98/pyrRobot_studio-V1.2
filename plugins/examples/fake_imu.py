# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""
Example plugin: publishes synthetic IMU readings at a fixed rate.
Demonstrates the minimum a plugin author needs to write.
"""

import random
import threading
import time

from sdk.pyrobot_plugin import Node, PluginManifest, PortSpec, PortDataType, ParamSpec


class FakeImuNode(Node):
    manifest = PluginManifest(
        id="pyrobot.examples.fake_imu",
        name="Fake IMU Source",
        category="Sensors (Examples)",
        description="Publishes synthetic IMU readings for testing.",
        outputs=[PortSpec("imu", PortDataType.IMU)],
        params=[ParamSpec(name="rate_hz", kind="number", default=50, min=1, max=500)],
        requires_urdf_link=True,
    )

    def on_start(self) -> None:
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def on_stop(self) -> None:
        self._stop.set()

    def on_params_changed(self, updated: dict) -> None:
        if "rate_hz" in updated:
            self._stop.set()
            self._thread.join(timeout=1.0)
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def _run(self) -> None:
        rate_hz = self.get_param("rate_hz", 50)
        period = 1.0 / rate_hz
        while not self._stop.is_set():
            self.emit("imu", {
                "accel": [random.uniform(-1, 1) for _ in range(3)],
                "gyro": [random.uniform(-0.1, 0.1) for _ in range(3)],
                "frame": self.urdf_link or "unknown",
            })
            self._stop.wait(period)
