# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""
Serial Device Reader — real device plugin using pyserial.

Reads line-delimited data from any serial port pyserial can open (a real
USB-serial adapter, an Arduino, a GPS module, etc.). If the configured
port cannot be opened, startup fails and the graph rolls back its start.

Each line is published as-is (as a string) plus a monotonic line counter;
parsing a specific device's protocol (NMEA, a custom telemetry format,
etc.) is expected to happen in a downstream Processing node, not here —
this plugin's job is just "get bytes off the wire reliably."
"""

import threading

from sdk.pyrobot_plugin import Node, PluginManifest, PortSpec, PortDataType, ParamSpec


class SerialReaderNode(Node):
    manifest = PluginManifest(
        id="pyrobot.devices.serial_reader",
        name="Serial Device Reader",
        category="Sensors",
        description="Reads line-delimited data from a serial port (USB-serial, Arduino, GPS module, etc.).",
        outputs=[PortSpec("line", PortDataType.STRING)],
        params=[
            ParamSpec(name="port", kind="string", default="/dev/ttyUSB0", description="Serial device path (e.g. /dev/ttyUSB0, COM3)"),
            ParamSpec(name="baudrate", kind="enum", default="9600", options=["9600", "19200", "38400", "57600", "115200"]),
            ParamSpec(name="timeout_s", kind="number", default=1.0, min=0.1, max=10.0),
        ],
    )

    def on_start(self) -> None:
        import serial

        self._stop = threading.Event()
        self._ser = None
        self._line_count = 0
        port = self.get_param("port", "/dev/ttyUSB0")
        try:
            self._ser = serial.Serial(
                port,
                baudrate=int(self.get_param("baudrate", "9600")),
                timeout=float(self.get_param("timeout_s", 1.0)),
            )
            self.log.info("opened serial port %s", port)
        except Exception as e:
            self.log.error("failed to open serial port %s: %s", port, e)
            raise RuntimeError(f"Serial device {port} could not be opened") from e

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def on_stop(self) -> None:
        self._stop.set()
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                raw = self._ser.readline()
            except Exception as e:
                self.log.error("serial read error: %s", e)
                if not self._stop.is_set():
                    self.fail(e)
                break
            if not raw:
                continue  # read timeout with no data — normal, keep polling
            captured = self.capture_time()
            self._line_count += 1
            try:
                text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            except Exception:
                text = repr(raw)
            self.emit("line", {"text": text, "line_number": self._line_count, "raw_byte_count": len(raw)}, timestamp=captured)
