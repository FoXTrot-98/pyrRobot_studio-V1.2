# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Browser keyboard lease; keys must be refreshed while the control pad has focus."""
import threading
import time
from sdk.pyrobot_plugin import Node, PluginManifest, PortSpec, PortDataType as T, ParamSpec


class KeyboardTeleop(Node):
    manifest = PluginManifest(id="pyrobot.control.keyboard", name="Keyboard teleoperation", category="Control",
        description="Hold W/A/S/D or arrow keys in Studio's control pad. Focus loss or a stale keyboard lease stops motion.",
        outputs=[PortSpec("cmd_vel", T.JSON, schema="pyrobot/VelocityCommand@1")],
        params=[ParamSpec("linear_speed", "number", default=.35, min=.05, max=.8),
                ParamSpec("angular_speed", "number", default=.8, min=.1, max=1.5)])
    KEYS = {"KeyW", "KeyA", "KeyS", "KeyD", "ArrowUp", "ArrowLeft", "ArrowDown", "ArrowRight", "Space"}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._keys_lock = threading.RLock()
        self._owner = None
        self._keys = set()
        self._received = 0.
        self._key_sequence = -1

    def on_start(self):
        with self._keys_lock:
            self._owner, self._keys, self._received = None, set(), 0.
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=self.node_id, daemon=True)
        self._thread.start()

    def acquire(self, owner):
        with self._keys_lock:
            if self._owner is not None:
                raise ValueError("Keyboard is already controlled by another browser tab")
            self._owner, self._key_sequence = owner, -1

    def accept_keys(self, owner, sequence, keys):
        if type(sequence) is not int or not isinstance(keys, list) or len(keys) > 9 or any(k not in self.KEYS for k in keys):
            raise ValueError("Invalid keyboard control packet")
        with self._keys_lock:
            if owner != self._owner or sequence <= self._key_sequence:
                raise ValueError("Expired keyboard lease or out-of-order packet")
            self._key_sequence, self._keys, self._received = sequence, set(keys), time.monotonic()

    def release(self, owner):
        with self._keys_lock:
            if self._owner == owner:
                self._keys, self._owner, self._received = set(), None, 0.

    def command(self):
        with self._keys_lock:
            keys = self._keys if time.monotonic()-self._received < .3 else set()
            if "Space" in keys:
                return 0., 0.
            linear = int(bool(keys & {"KeyW", "ArrowUp"})) - int(bool(keys & {"KeyS", "ArrowDown"}))
            angular = int(bool(keys & {"KeyA", "ArrowLeft"})) - int(bool(keys & {"KeyD", "ArrowRight"}))
            return linear*self.get_param("linear_speed", .35), angular*self.get_param("angular_speed", .8)

    def _run(self):
        try:
            while not self._stop.wait(.05):
                linear, angular = self.command()
                stamp = self.capture_time()
                self.emit("cmd_vel", {"linear": linear, "angular": angular, "time": stamp.as_seconds(),
                    "frame": self.robot_config.drive.base_frame}, timestamp=stamp)
        except Exception as exc:
            self.fail(exc)

    def on_stop(self):
        self._stop.set()
        with self._keys_lock:
            self._owner, self._keys = None, set()

    def on_params_changed(self, updated):
        pass
