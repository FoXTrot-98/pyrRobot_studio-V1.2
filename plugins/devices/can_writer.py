"""
CAN Bus Writer — the output-side counterpart to can_reader.py. Subscribes
to an input port and transmits each incoming message as a CAN frame.
Expected input payload shape: {"arbitration_id": int, "data_hex": str}
(same shape CanBusReaderNode emits, so a reader on one bus can feed a
writer on another for a bridge/relay setup).
"""

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
        ],
    )

    def on_start(self) -> None:
        import can

        self._bus = None
        try:
            self._bus = can.interface.Bus(
                channel=self.get_param("channel", "vcan0"),
                interface=self.get_param("interface", "virtual"),
            )
        except Exception as e:
            self.log.error("failed to open CAN bus for writing: %s", e)
            raise RuntimeError("CAN device could not be opened") from e

    def on_stop(self) -> None:
        if self._bus is not None:
            try:
                self._bus.shutdown()
            except Exception:
                pass

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
            self._bus.send(frame)
        except Exception as e:
            self.log.error("failed to send CAN frame: %s (payload=%s)", e, payload)
            raise RuntimeError(f"CAN send failed: {e}") from e
