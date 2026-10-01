# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""
CAN Bus Reader — real device plugin using python-can.

Works against ANY python-can-supported interface: 'socketcan' on Linux
with real hardware, 'virtual' for testing/CI without hardware, 'pcan',
'kvaser', etc. — the interface name is just a param, nothing here is
hardware-specific.

Publishes each received CAN frame as a bus message: arbitration_id, data
bytes (hex string, since raw bytes aren't JSON-safe), DLC, and whether it
was an extended-id / remote frame.
"""

import threading

from sdk.pyrobot_plugin import Node, PluginManifest, PortSpec, PortDataType, ParamSpec


class CanBusReaderNode(Node):
    manifest = PluginManifest(
        id="pyrobot.devices.can_reader",
        name="CAN Bus Reader",
        category="Sensors",
        description="Reads frames from a CAN bus (socketcan, virtual, or any python-can interface) and publishes them.",
        outputs=[PortSpec("frame", PortDataType.JSON)],
        params=[
            ParamSpec(name="channel", kind="string", default="vcan0", description="Interface channel name, e.g. 'can0' or 'vcan0'"),
            ParamSpec(name="interface", kind="enum", default="virtual", options=["virtual", "socketcan", "pcan", "kvaser", "vector"]),
            ParamSpec(name="bitrate", kind="number", default=500000, min=10000, max=1000000),
        ],
    )

    def on_start(self) -> None:
        import can

        self._stop = threading.Event()
        self._bus = None
        try:
            self._bus = can.interface.Bus(
                channel=self.get_param("channel", "vcan0"),
                interface=self.get_param("interface", "virtual"),
                bitrate=self.get_param("bitrate", 500000) if self.get_param("interface") != "virtual" else None,
            )
        except Exception as e:
            self.log.error("failed to open CAN bus (channel=%s, interface=%s): %s", self.get_param("channel"), self.get_param("interface"), e)
            raise RuntimeError("Device could not be opened") from e
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def on_stop(self) -> None:
        self._stop.set()
        if self._bus is not None:
            try:
                self._bus.shutdown()
            except Exception:
                pass

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                msg = self._bus.recv(timeout=0.5)
            except Exception as e:
                self.log.error("CAN recv error: %s", e)
                if not self._stop.is_set():
                    self.fail(e)
                break
            if msg is None:
                continue
            captured = self.capture_time()
            self.emit("frame", {
                "arbitration_id": msg.arbitration_id,
                "data_hex": msg.data.hex(),
                "dlc": msg.dlc,
                "is_extended_id": msg.is_extended_id,
                "is_remote_frame": msg.is_remote_frame,
                "timestamp": msg.timestamp,
            }, timestamp=captured)
