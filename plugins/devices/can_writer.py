# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""
CAN Bus Writer — the output-side counterpart to can_reader.py. Subscribes
to an input port and transmits each incoming message as a CAN frame.
Expected input payload shape: {"arbitration_id": int, "data_hex": str}
(same shape CanBusReaderNode emits, so a reader on one bus can feed a
writer on another for a bridge/relay setup).
"""

import queue
import threading
import time
from sdk.pyrobot_plugin import Node, PluginManifest, PortSpec, PortDataType, ParamSpec


class CanBusWriterNode(Node):
    manifest = PluginManifest(
        id="pyrobot.devices.can_writer",
        name="CAN Bus Writer",
        category="Output",
        description="Transmits incoming messages as CAN frames on a bus (socketcan, virtual, or any python-can interface).",
        inputs=[PortSpec("frame", PortDataType.JSON)],
        params=[
            ParamSpec(name="channel", kind="string", default="vcan0"),
            ParamSpec(name="interface", kind="enum", default="virtual", options=["virtual", "socketcan", "pcan", "kvaser", "vector"]),
            ParamSpec(name="send_timeout", kind="number", default=0.1, min=0.001, max=1.0),
            ParamSpec(name="max_queue_age", kind="number", default=0.25, min=0.01, max=5.0),
        ],
    )

    def on_start(self) -> None:
        import can

        self._bus = None
        self._stop = threading.Event()
        self._queue = queue.Queue(maxsize=64)
        try:
            self._bus = can.interface.Bus(
                channel=self.get_param("channel", "vcan0"),
                interface=self.get_param("interface", "virtual"),
            )
        except Exception as e:
            self.log.error("failed to open CAN bus for writing: %s", e)
            raise RuntimeError("CAN device could not be opened") from e
        self._thread = threading.Thread(target=self._send_loop, name=self.node_id, daemon=True)
        self._thread.start()

    def on_stop(self) -> None:
        if hasattr(self, '_stop'):
            self._stop.set()
        # The worker owns the device and closes it after any bounded send.

    def on_message(self, port: str, message) -> None:
        if port != "frame" or self._bus is None:
            return
        import can

        payload = message.payload
        try:
            frame = can.Message(
                arbitration_id=int(payload["arbitration_id"]),
                data=bytes.fromhex(payload["data_hex"]),
                is_extended_id=bool(payload.get("is_extended_id", False)),
            )
            # Never perform driver I/O on the shared message-bus thread.
            self._queue.put_nowait((time.monotonic(), frame))
        except Exception as e:
            self.log.error("failed to send CAN frame: %s (payload=%s)", e, payload)
            raise RuntimeError(f"CAN send failed: {e}") from e

    def _send_loop(self):
        try:
            while not self._stop.is_set():
                try:
                    received, frame = self._queue.get(timeout=.05)
                except queue.Empty:
                    continue
                if self._stop.is_set():
                    break
                if time.monotonic() - received > self.get_param('max_queue_age', .25):
                    raise RuntimeError('CAN command expired in transmit queue')
                self._bus.send(frame, timeout=self.get_param('send_timeout', .1))
        except Exception as exc:
            if not self._stop.is_set():
                self.fail(exc)
        finally:
            try:
                self._bus.shutdown()
            except Exception as exc:
                self.fail(exc)
