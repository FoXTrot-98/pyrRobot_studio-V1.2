"""Explicit mode selection, fresh commands only, zero output during transitions."""
import threading
import time
from sdk.pyrobot_plugin import Node, PluginManifest, PortSpec, PortDataType as T, ParamSpec


class CommandSelector(Node):
    manifest = PluginManifest(id="pyrobot.control.selector", name="Drive mode selector", category="Control",
        description="Select manual, autonomous or stopped. Mode switches discard queued commands; stale sources stop motion.",
        inputs=[PortSpec("manual", T.JSON, schema="pyrobot/VelocityCommand@1"),
                PortSpec("autonomous", T.JSON, schema="pyrobot/VelocityCommand@1")],
        outputs=[PortSpec("cmd_vel", T.JSON, schema="pyrobot/VelocityCommand@1")],
        params=[ParamSpec("mode", "enum", default="stopped", options=["stopped", "manual", "autonomous"])])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._command_lock = threading.RLock()
        self._commands = {}
        self._mode_since = None

    def on_start(self):
        self._commands.clear()
        self._mode_since = self.bus._clock.now().epoch_ns
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=self.node_id, daemon=True)
        self._thread.start()

    def on_message(self, port, message):
        with self._command_lock:
            publication = message.published_timestamp or message.timestamp
            age = self.bus._clock.now().delta(publication)
            if (self._mode_since is not None and publication.epoch_ns <= self._mode_since) or not 0 <= age < .4:
                return
            previous = self._commands.get(port)
            if previous:
                previous_stamp = previous[1].published_timestamp or previous[1].timestamp
                if publication.epoch_ns <= previous_stamp.epoch_ns:
                    return
            self._commands[port] = (time.monotonic()-age, message)

    def _publish(self):
        mode = self.get_param("mode", "stopped")
        entry = self._commands.get(mode)
        if entry and time.monotonic()-entry[0] < .4:
            with self.processing(entry[1]):
                self.emit("cmd_vel", entry[1].payload)
        else:
            self.emit("cmd_vel", {"linear": 0., "angular": 0., "time": self.capture_time().as_seconds(),
                "frame": self.robot_config.drive.base_frame})

    def _run(self):
        try:
            while not self._stop.wait(.05):
                with self._command_lock:
                    self._publish()
        except Exception as exc:
            self.fail(exc)

    def update_params(self, updates):
        # Protect the parameter mutation itself, not just its notification.
        with self._command_lock:
            super().update_params(updates)

    def on_params_changed(self, updated):
        with self._command_lock:
            self._mode_since = self.bus._clock.now().epoch_ns
            self._commands.clear()
            self._publish()

    def on_stop(self):
        self._stop.set()
