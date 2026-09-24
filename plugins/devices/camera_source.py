"""
Camera Source — real device plugin using OpenCV.

Tries to open an actual camera via cv2.VideoCapture(device_index).
Synthetic fallback must be enabled explicitly for development. Hardware
failure otherwise fails startup or marks the running node as failed.

Frames are published as base64-encoded JPEG (JSON-safe) — fine for
preview/debug throughput; a high-bandwidth binary channel is future work
noted in the README, since the bus payload format is JSON today.
"""

import base64
import threading
import time

import cv2
import numpy as np

from sdk.pyrobot_plugin import Node, PluginManifest, PortSpec, PortDataType, ParamSpec


class CameraSourceNode(Node):
    manifest = PluginManifest(
        id="pyrobot.devices.camera_source",
        name="Camera Source",
        category="Sensors",
        description="Captures frames from a camera (OpenCV). Falls back to a synthetic test pattern if no camera hardware is found.",
        outputs=[PortSpec("frame", PortDataType.IMAGE, schema="pyrobot/Image@1")],
        params=[
            ParamSpec(name="allow_synthetic", kind="bool", default=False,
                      description="Enable generated test frames when a camera is unavailable (development only)."),
            ParamSpec(name="device_index", kind="number", default=0, min=0, max=16),
            ParamSpec(name="width", kind="number", default=320, min=64, max=1920),
            ParamSpec(name="height", kind="number", default=240, min=48, max=1080),
            ParamSpec(name="rate_hz", kind="number", default=15, min=1, max=60),
        ],
        requires_urdf_link=True,
    )

    def on_start(self) -> None:
        self._stop = threading.Event()
        self._cap = None
        self._synthetic_frame_index = 0

        device_index = int(self.get_param("device_index", 0))
        width = int(self.get_param("width", 320))
        height = int(self.get_param("height", 240))

        cap = cv2.VideoCapture(device_index)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            ok, _ = cap.read()
            if ok:
                self._cap = cap
                self.log.info("camera device %d opened at %dx%d", device_index, width, height)
            else:
                cap.release()

        if self._cap is None:
            cap.release()
            if not self.get_param("allow_synthetic", False):
                raise RuntimeError("Camera unavailable. Connect a camera or explicitly enable allow_synthetic for development.")
            self.log.warning(
                "no camera at device_index=%d (or read failed) — publishing a synthetic test pattern instead",
                device_index,
            )

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def on_stop(self) -> None:
        self._stop.set()
        if self._cap is not None:
            self._cap.release()

    def _synthetic_frame(self, width: int, height: int) -> np.ndarray:
        # a moving diagonal gradient bar pattern — enough to prove frames
        # are actually changing over time, not a static placeholder image
        self._synthetic_frame_index += 1
        x = np.linspace(0, 255, width, dtype=np.int16)
        y = np.linspace(0, 255, height, dtype=np.int16)
        base = np.add.outer(y, x) % 256  # int16 arithmetic — no uint8 overflow
        shift = (self._synthetic_frame_index * 4) % 256
        frame = ((base + shift) % 256).astype(np.uint8)
        return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

    def _run(self) -> None:
        rate_hz = self.get_param("rate_hz", 15)
        width = int(self.get_param("width", 320))
        height = int(self.get_param("height", 240))
        period = 1.0 / rate_hz

        while not self._stop.is_set():
            if self._cap is not None:
                ok, frame = self._cap.read()
                source = "camera"
                if not ok:
                    if not self.get_param("allow_synthetic", False):
                        self.fail("Camera stopped delivering frames")
                        self.log.error(self.error)
                        break
                    frame = self._synthetic_frame(width, height)
                    source = "synthetic-fallback"
            else:
                frame = self._synthetic_frame(width, height)
                source = "synthetic"

            captured = self.capture_time()
            ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if ok:
                self.emit("frame", {
                    "jpeg_base64": base64.b64encode(encoded.tobytes()).decode("ascii"),
                    "width": frame.shape[1],
                    "height": frame.shape[0],
                    "source": source,
                    "frame_link": self.urdf_link,
                    "frame": self.urdf_link,
                    "time": captured.as_seconds(),
                }, timestamp=captured)
            self._stop.wait(period)
