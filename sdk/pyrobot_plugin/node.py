"""
Base classes for PyRobot Studio plugins.

A minimal user plugin looks like:

    from pyrobot_plugin import Node, PluginManifest, PortSpec, PortDataType

    class MyFilterNode(Node):
        manifest = PluginManifest(
            id="myorg.my_filter",
            name="My Filter",
            category="Processing",
            inputs=[PortSpec("in", PortDataType.IMAGE)],
            outputs=[PortSpec("out", PortDataType.IMAGE)],
        )

        def on_message(self, port: str, message):
            result = do_something(message.payload)
            self.emit("out", result)

Plugin discovery: any Node subclass found in an importable module under a
configured plugins directory (or installed as a `pyrobot-plugin` entry
point) is auto-registered. No manual wiring needed.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import replace
from contextlib import contextmanager
from abc import ABC
from typing import Any, Optional

from core.bus.base import Bus, BusMessage
from .manifest import PluginManifest
from core.messages import validate_payload
from core.simulation.config import RobotConfiguration


class Node(ABC):
    """Base class every plugin node inherits from. Handles bus wiring so
    subclasses only implement on_message / on_start / on_stop."""

    manifest: PluginManifest  # subclasses MUST set this as a class attribute

    def __init__(self, node_id: str, bus: Bus, params: Optional[dict] = None, urdf_link: Optional[str] = None):
        if not hasattr(self, "manifest") or self.manifest is None:
            raise NotImplementedError(f"{type(self).__name__} must define a class-level `manifest`")
        self.node_id = node_id
        self.bus = bus
        self.params = params or {}
        self.urdf_link = urdf_link  # bound URDF frame, if manifest.requires_urdf_link
        self.log = logging.getLogger(f"pyrobot.node.{self.manifest.id}.{node_id}")
        self._input_topics = {port.name: f"node/{node_id}/in/{port.name}" for port in self.manifest.inputs}
        self._output_topics = {port.name: f"node/{node_id}/out/{port.name}" for port in self.manifest.outputs}
        self._input_specs = {port.name: port for port in self.manifest.inputs}
        self._output_specs = {port.name: port for port in self.manifest.outputs}
        self._running = False
        self._subscriptions = []
        self.state = "stopped"
        self.error = None
        self.robot_model = None  # injected by the runtime before startup
        self.robot_config = RobotConfiguration()
        self._context = threading.local()
        self._publication_lock = threading.RLock()
        self._pending = []
        self._staged = False
        self._sequence = 0
        self.run_id = None

    # -- lifecycle hooks (override as needed) -----------------------------

    def validate_configuration(self):
        """Check configuration without opening devices or publishing."""

    def on_start(self) -> None:
        """Called once when the node graph starts running."""

    def on_stop(self) -> None:
        """Called once when the node graph stops."""

    def on_message(self, port: str, message: BusMessage) -> None:
        """Called for every message arriving on any input port.
        `port` is the input port name (matches manifest.inputs[i].name)."""

    # -- internals ----------------------------------------------------------

    def start(self, *, staged=False) -> None:
        if self._running:
            return
        previous_worker = getattr(self, "_thread", None)
        if previous_worker and previous_worker.is_alive():
            raise RuntimeError("Previous worker is still running; cannot restart this node")
        self.state, self.error = "starting", None
        self._staged = staged
        self._pending.clear()
        self._running = True
        try:
            for port_name, topic in self._input_topics.items():
                self._subscriptions.append(self.bus.subscribe(
                    topic, lambda msg, p=port_name: self._receive(p, msg), exact=True))
            self.on_start()
            with self._publication_lock:
                if self.state == "failed":
                    raise RuntimeError(self.error)
                self.state = "running"
        except Exception as exc:
            try:
                self.stop()
            except Exception:
                self.log.exception("Cleanup after failed start")
            self.state, self.error = "failed", str(exc)
            raise

    def _receive(self, port, message):
        if self.run_id is not None and message.run_id != self.run_id:
            return  # An earlier execution must not contaminate a restarted clock/map.
        if self._running and self.state == "running":
            try:
                spec = self._input_specs[port]
                if spec.schema and message.schema != spec.schema:
                    raise ValueError(f"{port}: expected {spec.schema}, received {message.schema}")
                payload = validate_payload(spec.schema, message.payload)
                with self.processing(message):
                    self.on_message(port, replace(message, payload=payload))
            except Exception as exc:
                self.fail(exc)
                raise

    @contextmanager
    def processing(self, message):
        previous = getattr(self._context, "message", None)
        self._context.message = message
        try:
            yield
        finally:
            self._context.message = previous

    def fail(self, error):
        with self._publication_lock:
            self.state, self.error = "failed", str(error)
        event = getattr(self, "_stop", None)
        if event is not None:
            event.set()

    def request_stop(self):
        with self._publication_lock:
            self._running = False
        event = getattr(self, "_stop", None)
        if event is not None:
            event.set()

    def capture_time(self, simulation_seconds=None):
        """Call at sensor capture, before encoding or processing."""
        with self._publication_lock:
            self._sequence += 1
            stamp = replace(self.bus._clock.now(), source_id=self.node_id, sequence=self._sequence)
            if simulation_seconds is not None:
                stamp = replace(stamp, epoch_ns=round(simulation_seconds * 1e9))
            return stamp

    def release_startup(self):
        with self._publication_lock:
            if not self._running or self.state == "failed":
                raise RuntimeError(self.error or "Node stopped during startup")
            self._staged = False
            pending, self._pending = self._pending, []
            for args, kwargs in pending:
                self.bus.publish(*args, **kwargs)

    def stop(self) -> None:
        worker = getattr(self, "_thread", None)
        if not self._running and not self._subscriptions and self.state == "stopped" and not (worker and worker.is_alive()):
            return
        self._running = False
        failed = self.state == "failed"
        self._pending.clear()
        for subscription in self._subscriptions:
            subscription.close()
        self._subscriptions.clear()
        try:
            self.on_stop()
            worker = getattr(self, "_thread", None)
            if worker and worker is not threading.current_thread():
                worker.join(timeout=3)
                if worker.is_alive():
                    raise RuntimeError("Node worker did not stop within 3 seconds")
            self.state = "failed" if failed else "stopped"
        except Exception as exc:
            self.state, self.error = "failed", str(exc)
            raise

    def emit(self, output_port: str, payload: dict, *, timestamp=None, clock_domain=None) -> None:
        """Publish on one of this node's declared output ports."""
        if output_port not in self._output_topics:
            raise ValueError(
                f"'{output_port}' is not a declared output of {self.manifest.id} "
                f"(declared: {list(self._output_topics)})"
            )
        if self._running and self.state != "failed":
            try:
                spec = self._output_specs[output_port]
                payload = validate_payload(spec.schema, payload)
                source = getattr(self._context, "message", None)
                publication = self.capture_time()
                capture = timestamp or (source.timestamp if source else publication)
                domain = clock_domain or (source.clock_domain if source else "session")
                args = (self._output_topics[output_port], payload)
                kwargs = dict(timestamp=capture, published_timestamp=publication, clock_domain=domain, schema=spec.schema, run_id=self.run_id)
                with self._publication_lock:
                    if not self._running or self.state == "failed":
                        return
                    if self._staged:
                        if len(self._pending) >= 1024:
                            raise RuntimeError("Startup publication buffer exceeded 1024 messages")
                        self._pending.append((args, kwargs))
                    else:
                        self.bus.publish(*args, **kwargs)
            except Exception as exc:
                self.fail(exc)
                raise

    def get_param(self, name: str, default: Any = None) -> Any:
        return self.params.get(name, default)

    def update_params(self, updates: dict) -> None:
        """Apply new values onto this node's params while it's running,
        then notify the subclass via on_params_changed so it can react
        (e.g. a source node adjusting its capture rate without a restart).
        Only keys already declared in the manifest are accepted — the
        graph layer (see backend/app/graph.py) validates keys against the
        manifest before calling this."""
        previous = self.params.copy()
        self.params.update(updates)
        try:
            if self._running:
                self.on_params_changed(updates)
        except Exception:
            self.params.clear()
            self.params.update(previous)
            raise

    def on_params_changed(self, updated: dict) -> None:
        """Default: restart to apply device configuration. Override for
        plugins that can apply updates without restarting."""

        self.stop()
        self.start()
