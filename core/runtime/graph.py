"""
NodeGraph: the running pipeline.

A graph is a set of node instances (each an instance of some registered
plugin's Node subclass) plus a set of connections between their ports.

Connection mechanics: each Node publishes on a fixed topic
`node/<id>/out/<port>` and subscribes on `node/<id>/in/<port>` (see
sdk/pyrobot_plugin/node.py). A "connection" between node A's output and
node B's input is implemented as a bridge subscription: the graph
subscribes to A's output topic and republishes every message onto B's
input topic. This keeps individual Node implementations completely
unaware of the graph topology — they just publish/subscribe on their own
named ports — while letting the graph be reconfigured (rewired) without
touching plugin code.
"""

from __future__ import annotations

import logging
import math
import re
import threading
import uuid
import json
import time
from functools import wraps
from dataclasses import dataclass
from typing import Optional

from core.bus.base import Bus
from core.timing.clock import PRTClock
from .plugin_registry import PluginRegistry
from core.messages import SCHEMAS
from core.simulation.config import RobotConfiguration

logger = logging.getLogger("pyrobot.graph")


@dataclass
class NodeInstance:
    node_id: str
    plugin_id: str
    params: dict
    urdf_link: Optional[str]
    node_obj: object  # the live Node instance


@dataclass
class Connection:
    from_node: str
    from_port: str
    to_node: str
    to_port: str

    @property
    def key(self) -> str:
        return f"{self.from_node}.{self.from_port}->{self.to_node}.{self.to_port}"


class GraphError(Exception):
    pass


def synchronized(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapped


class NodeGraph:
    def __init__(self, bus: Bus, registry: PluginRegistry, clock_factory=None):
        self._lock = threading.RLock()
        self._bridges = {}
        self.bus = bus
        self.registry = registry
        self._clock_factory = clock_factory or (lambda source_id: PRTClock(source_id=source_id))
        self.nodes: dict[str, NodeInstance] = {}
        self.connections: dict[str, Connection] = {}
        self._running = False
        self.robot_model = None
        self.robot_config = RobotConfiguration()
        self._supervisor_stop = threading.Event()
        self.failure_reason = None
        self.run_id = None

    # -- node management ----------------------------------------------------

    @synchronized
    def add_node(self, node_id: str, plugin_id: str, params: Optional[dict] = None, urdf_link: Optional[str] = None) -> NodeInstance:
        if self._running:
            raise GraphError("Stop the graph before adding nodes")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", node_id):
            raise GraphError("Node IDs may contain only letters, digits, underscores and hyphens")
        if node_id in self.nodes:
            raise GraphError(f"node id '{node_id}' already exists in graph")
        entry = self.registry.get(plugin_id)  # raises KeyError -> caller maps to 404
        if entry.manifest.requires_urdf_link and not urdf_link:
            raise GraphError(f"plugin '{plugin_id}' requires a urdf_link binding but none was given")

        params = {p.name: p.default for p in entry.manifest.params} | (params or {})
        self._validate_params(entry.manifest, params)
        node_obj = entry.node_class(
            node_id=node_id,
            bus=self.bus,
            params=params or {},
            urdf_link=urdf_link,
        )
        node_obj.robot_model = self.robot_model
        node_obj.robot_config = self.robot_config
        instance = NodeInstance(node_id=node_id, plugin_id=plugin_id, params=params or {}, urdf_link=urdf_link, node_obj=node_obj)
        self.nodes[node_id] = instance
        logger.info("added node '%s' (plugin=%s)", node_id, plugin_id)
        return instance

    @synchronized
    def update_node_params(self, node_id: str, updates: dict) -> NodeInstance:
        if node_id not in self.nodes:
            raise GraphError(f"no such node '{node_id}'")
        instance = self.nodes[node_id]
        manifest = self.registry.get(instance.plugin_id).manifest
        self._validate_params(manifest, updates)
        from sdk.pyrobot_plugin.node import Node
        restart = self._running and type(instance.node_obj).on_params_changed is Node.on_params_changed
        previous = instance.node_obj.params.copy()
        try:
            if restart:
                self.stop()
            instance.node_obj.update_params(updates)
            if restart:
                self.start()
        except Exception as exc:
            instance.node_obj.params = previous
            instance.params = previous.copy()
            raise GraphError(f"Parameter update failed: {exc}") from exc
        instance.params = instance.node_obj.params.copy()
        logger.info("updated params on '%s': %s", node_id, updates)
        return instance

    @synchronized
    def remove_node(self, node_id: str) -> None:
        if node_id not in self.nodes:
            raise GraphError(f"no such node '{node_id}'")
        instance = self.nodes[node_id]
        if self._running:
            self.stop()
        try:
            instance.node_obj.stop()
        except Exception as exc:
            raise GraphError(f"Failed to stop {node_id}: {exc}") from exc
        del self.nodes[node_id]
        stale = [c for c in self.connections.values() if c.from_node == node_id or c.to_node == node_id]
        for c in stale:
            self.disconnect(c.from_node, c.from_port, c.to_node, c.to_port)
        logger.info("removed node '%s' (and %d dependent connection(s))", node_id, len(stale))

    # -- connections ----------------------------------------------------------

    @synchronized
    def connect(self, from_node: str, from_port: str, to_node: str, to_port: str) -> Connection:
        if self._running:
            raise GraphError("Stop the graph before connecting nodes")
        for name, node_id in (("from_node", from_node), ("to_node", to_node)):
            if node_id not in self.nodes:
                raise GraphError(f"{name} '{node_id}' does not exist in graph")

        src_manifest = self.registry.get(self.nodes[from_node].plugin_id).manifest
        dst_manifest = self.registry.get(self.nodes[to_node].plugin_id).manifest
        if not any(p.name == from_port for p in src_manifest.outputs):
            raise GraphError(f"node '{from_node}' (plugin {src_manifest.id}) has no output port '{from_port}'")
        if not any(p.name == to_port for p in dst_manifest.inputs):
            raise GraphError(f"node '{to_node}' (plugin {dst_manifest.id}) has no input port '{to_port}'")

        src = next(p for p in src_manifest.outputs if p.name == from_port)
        dst = next(p for p in dst_manifest.inputs if p.name == to_port)
        if src.data_type != dst.data_type and "any" not in (src.data_type.value, dst.data_type.value):
            raise GraphError(f"Incompatible ports: {src.data_type.value} -> {dst.data_type.value}")
        if dst.schema and src.schema != dst.schema:
            raise GraphError(f"Incompatible schemas: {from_node}.{from_port} ({src.schema or 'untyped'}) -> {to_node}.{to_port} ({dst.schema})")
        if any(c.to_node == to_node and c.to_port == to_port for c in self.connections.values()):
            raise GraphError(f"Input {to_node}.{to_port} already has a source; use an explicit merge/arbitration node")

        conn = Connection(from_node=from_node, from_port=from_port, to_node=to_node, to_port=to_port)
        if conn.key in self.connections:
            raise GraphError(f"connection already exists: {conn.key}")

        src_topic = f"node/{from_node}/out/{from_port}"
        dst_topic = f"node/{to_node}/in/{to_port}"

        def _bridge(msg, dst_topic=dst_topic):
            if self._running and msg.run_id == self.run_id:
                self.bus.publish(dst_topic, msg.payload, timestamp=msg.timestamp,
                    published_timestamp=msg.published_timestamp, clock_domain=msg.clock_domain, schema=msg.schema, run_id=msg.run_id)

        self._bridges[conn.key] = self.bus.subscribe(src_topic, _bridge, exact=True)
        self.connections[conn.key] = conn
        logger.info("connected %s", conn.key)
        return conn

    # -- lifecycle ----------------------------------------------------------

    @synchronized
    def preflight(self):
        diagnostics = []
        connected = {(c.to_node, c.to_port) for c in self.connections.values()}
        for name, instance in self.nodes.items():
            node = instance.node_obj
            for port in node.manifest.inputs:
                if port.required and (name, port.name) not in connected:
                    diagnostics.append({"node_id": name, "port": port.name,
                        "message": f"Connect required input {name}.{port.name}"})
            for port in node.manifest.inputs + node.manifest.outputs:
                if port.schema and port.schema not in SCHEMAS:
                    diagnostics.append({"node_id": name, "port": port.name,
                        "message": f"Unknown schema {port.schema}"})
            try:
                node.validate_configuration()
            except Exception as exc:
                diagnostics.append({"node_id": name, "port": None, "message": str(exc)})
        return diagnostics

    @synchronized
    def disconnect(self, from_node, from_port, to_node, to_port):
        key = Connection(from_node, from_port, to_node, to_port).key
        if key not in self.connections:
            raise GraphError(f"No such connection: {key}")
        if self._running:
            self.stop()
        self._bridges.pop(key).close()
        del self.connections[key]

    @synchronized
    def start(self) -> None:
        if self._running:
            return
        diagnostics = self.preflight()
        if diagnostics:
            raise GraphError("Preflight failed: " + "; ".join(d["message"] for d in diagnostics))
        self.failure_reason = None
        self.run_id = uuid.uuid4().hex
        for instance in self.nodes.values():
            instance.node_obj.run_id = self.run_id
        started = []
        try:
            # Start consumers first to reduce initial data loss.
            for instance in sorted(self.nodes.values(), key=lambda n: not bool(n.node_obj.manifest.inputs)):
                instance.node_obj.start(staged=True)
                started.append(instance)
            topics = [topic for n in self.nodes.values() for topic in
                      (*n.node_obj._input_topics.values(), *n.node_obj._output_topics.values())]
            self.bus.wait_ready(topics)
            for instance in started:
                if instance.node_obj.state == "failed":
                    raise RuntimeError(f"{instance.node_id}: {instance.node_obj.error}")
            self._running = True
            for instance in started:
                instance.node_obj.release_startup()
            self._supervisor_stop = threading.Event()
            threading.Thread(target=self._supervise, args=(self._supervisor_stop,),
                name="pyrobot-supervisor", daemon=True).start()
        except Exception as exc:
            self._running = False
            for instance in reversed(started):
                try:
                    instance.node_obj.stop()
                except Exception:
                    logger.exception("Startup rollback failed for %s", instance.node_id)
            raise GraphError(f"Graph startup failed: {exc}") from exc

    def _supervise(self, stopped):
        # Conservative policy: any failure stops the whole control graph.
        # Never run joins on a bus callback or on the failed worker itself.
        while not stopped.wait(.05):
            with self._lock:
                if stopped.is_set():
                    return
                transport = self.bus._transport
                if getattr(transport, '_error', None) is not None or (
                    hasattr(transport, 'last_progress') and time.monotonic() - transport.last_progress > 2.
                ):
                    self.failure_reason = 'Message transport failed or made no progress for 2 seconds'
                    try:
                        self.stop()
                    except Exception:
                        logger.exception('Transport failure cleanup')
                    return
                for instance in self.nodes.values():
                    node = instance.node_obj
                    worker = getattr(node, "_thread", None)
                    if node._running and node.state == "running" and worker and not worker.is_alive():
                        node.fail("Worker exited unexpectedly")
                failed = [n for n in self.nodes.values() if n.node_obj.state == "failed"]
                if failed:
                    self.failure_reason = "; ".join(f"{n.node_id}: {n.node_obj.error}" for n in failed)
                    try:
                        self.stop()
                    except Exception:
                        logger.exception("Failure containment cleanup")
                    return

    @synchronized
    def stop(self) -> None:
        self._running = False
        self._supervisor_stop.set()
        # Close every publication gate before waiting on any worker.
        for instance in self.nodes.values():
            instance.node_obj.request_stop()
        errors = []
        for instance in reversed(list(self.nodes.values())):
            try:
                instance.node_obj.stop()
            except Exception as exc:
                errors.append(f"{instance.node_id}: {exc}")
        if errors:
            raise GraphError("Failed to stop nodes: " + "; ".join(errors))

    @synchronized
    def close(self):
        try:
            self.stop()
        finally:
            for handle in self._bridges.values():
                handle.close()
            self._bridges.clear()
            self.connections.clear()

    @staticmethod
    def _validate_params(manifest, updates):
        declared = {p.name: p for p in manifest.params}
        unknown = set(updates) - declared.keys()
        if unknown:
            raise GraphError(f"Unknown parameters: {sorted(unknown)}")
        for name, value in updates.items():
            p = declared[name]
            valid = True
            if p.kind == "number":
                valid = type(value) in (int, float) and math.isfinite(value)
                if valid:
                    valid = (p.min is None or value >= p.min) and (p.max is None or value <= p.max)
            elif p.kind == "bool":
                valid = type(value) is bool
            elif p.kind in ("string", "file"):
                valid = isinstance(value, str)
            elif p.kind == "enum":
                valid = value in (p.options or [])
            elif p.kind == "json":
                try:
                    json.dumps(value, allow_nan=False)
                except (ValueError, TypeError):
                    valid = False
            if not valid:
                raise GraphError(f"Invalid value for parameter '{name}': {value!r}")

    # -- serialization ----------------------------------------------------------

    @synchronized
    def to_dict(self) -> dict:
        return {
            "running": self._running,
            "failure_reason": self.failure_reason,
            "run_id": self.run_id,
            "nodes": [
                {
                    "node_id": n.node_id,
                    "plugin_id": n.plugin_id,
                    "params": n.params.copy(),
                    "state": n.node_obj.state,
                    "error": n.node_obj.error,
                    "urdf_link": n.urdf_link,
                }
                for n in self.nodes.values()
            ],
            "connections": [
                {"from_node": c.from_node, "from_port": c.from_port, "to_node": c.to_node, "to_port": c.to_port}
                for c in self.connections.values()
            ],
        }
