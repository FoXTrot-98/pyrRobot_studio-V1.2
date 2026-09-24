"""Behavioral regressions for contracts, startup, clocks and failure containment."""
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_runtime_projects import MemoryTransport
from core.bus.base import Bus, BusMessage
from core.timing.clock import PRTClock
from core.messages import validate_payload
from core.runtime.graph import NodeGraph, GraphError
from core.runtime.plugin_registry import PluginRegistry, PluginEntry
from core.runtime.session import Runtime
from core.runtime.project import ProjectDocument, export_project, prepare_project
from core.simulation.worker import WorkerNode
from core.simulation.config import RobotConfiguration
from core.simulation.world import robot_dimensions, FourWheelSimulator, camera_image
from core.urdf.model import parse_urdf
from sdk.pyrobot_plugin import Node, PluginManifest, PortSpec, PortDataType as T

COMMAND = "pyrobot/VelocityCommand@1"


class Once(Node):
    manifest = PluginManifest(id="test.once", name="Once", category="Test",
        outputs=[PortSpec("out", T.JSON, schema=COMMAND)])

    def on_start(self):
        self.emit("out", {"linear": .2, "angular": 0., "time": 1.25},
            timestamp=self.capture_time(1.25), clock_domain="simulation")


class Relay(WorkerNode):
    manifest = PluginManifest(id="test.relay", name="Relay", category="Test",
        inputs=[PortSpec("in", T.JSON, schema=COMMAND)],
        outputs=[PortSpec("out", T.JSON, schema=COMMAND)])

    def on_start(self):
        self.start_worker()

    def process(self, port, payload):
        self.emit("out", payload)


class Sink(Node):
    manifest = PluginManifest(id="test.sink", name="Sink", category="Test",
        inputs=[PortSpec("in", T.JSON, schema=COMMAND)])

    def on_start(self):
        self.received = []

    def on_message(self, port, message):
        self.received.append(message)


class Explodes(Sink):
    manifest = PluginManifest(id="test.explodes", name="Explodes", category="Test",
        inputs=[PortSpec("in", T.JSON, schema=COMMAND)])

    def on_message(self, port, message):
        raise RuntimeError("injected device fault")


def register(registry):
    for cls in (Once, Relay, Sink, Explodes):
        registry._entries[cls.manifest.id] = PluginEntry(cls.manifest, cls, Path(__file__))


def wait_until(predicate, timeout=3):
    deadline = time.monotonic()+timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Timed out waiting for runtime state")
        time.sleep(.01)


class HardeningTests(unittest.TestCase):
    def setUp(self):
        clock = PRTClock("test-runtime")
        clock.set_epoch_origin(time.time_ns())
        self.bus = Bus(MemoryTransport(), clock)
        registry = PluginRegistry()
        register(registry)
        self.graph = NodeGraph(self.bus, registry)

    def tearDown(self):
        self.graph.close()
        self.bus.close()

    def connect_pair(self, sink="test.sink"):
        self.graph.add_node("source", "test.once")
        target = self.graph.add_node("sink", sink).node_obj
        self.graph.connect("source", "out", "sink", "in")
        return target

    def test_required_inputs_block_start_before_any_node_runs(self):
        self.graph.add_node("source", "test.once")
        self.graph.add_node("sink", "test.sink")
        self.assertEqual(self.graph.preflight()[0]["port"], "in")
        with self.assertRaisesRegex(GraphError, "sink.in"):
            self.graph.start()
        self.assertTrue(all(n.node_obj.state == "stopped" for n in self.graph.nodes.values()))

    def test_schema_mismatch_rejected_even_between_json_ports(self):
        class ScanSink(Sink):
            manifest = PluginManifest(id="test.scan", name="Scan", category="Test",
                inputs=[PortSpec("in", T.JSON, schema="pyrobot/LaserScan@1")])
        self.graph.registry._entries["test.scan"] = PluginEntry(ScanSink.manifest, ScanSink, Path(__file__))
        self.graph.add_node("source", "test.once")
        self.graph.add_node("scan", "test.scan")
        with self.assertRaisesRegex(GraphError, "Incompatible schemas"):
            self.graph.connect("source", "out", "scan", "in")

    def test_payload_units_versions_shapes_and_nonfinite_values_rejected(self):
        valid = {"linear": 1., "angular": 0., "time": 0.}
        for updates in ({"linear": float("nan")}, {"linear": "fast"}, {"linear_unit": "km/h"},
                        {"schema_version": 2}, {"frame": ""}, {"unknown": 1}):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                validate_payload(COMMAND, valid | updates)
        with self.assertRaises(ValueError):
            validate_payload("pyrobot/LaserScan@1", {"ranges": [1.], "angles": [], "hits": [True], "range_max": 9., "offset": [0.,0.,0.]})
        with self.assertRaises(ValueError):
            validate_payload("pyrobot/OccupancyGrid@1", {"grid": [[0,1],[0]], "origin": [0.,0.], "resolution": .1, "time": 0.})

    def test_one_shot_startup_and_restarts_deliver_exactly_once(self):
        sink = self.connect_pair()
        for _ in range(3):
            self.graph.start()
            self.assertEqual(len(sink.received), 1)
            self.graph.stop()

    def test_readiness_failure_discards_staged_publications(self):
        sink = self.connect_pair()
        with patch.object(self.bus, "wait_ready", side_effect=TimeoutError("route unavailable")):
            with self.assertRaisesRegex(GraphError, "route unavailable"):
                self.graph.start()
        self.assertEqual(sink.received, [])
        self.assertTrue(all(not n.node_obj._running for n in self.graph.nodes.values()))

    def test_invalid_input_stops_whole_graph_and_preserves_diagnostic(self):
        sink = self.connect_pair()
        self.graph.start()
        with self.assertRaises(ValueError):
            self.bus.publish("node/sink/in/in", {"linear": "bad"}, schema=COMMAND, run_id=self.graph.run_id)
        wait_until(lambda: not self.graph.to_dict()["running"])
        self.assertEqual(sink.state, "failed")
        self.assertTrue(self.graph.failure_reason)
        self.assertFalse(self.graph.nodes["source"].node_obj._running)
        before = len(sink.received)
        self.graph.nodes["source"].node_obj.emit("out", {"linear": 1, "angular": 0, "time": 2})
        self.assertEqual(len(sink.received), before)

    def test_wall_clock_adjustment_does_not_reverse_session_time(self):
        clock = self.bus._clock
        before = clock.now()
        with patch("core.timing.clock.time.time_ns", return_value=0):
            after = clock.now()
        self.assertGreaterEqual(after.epoch_ns, before.epoch_ns)

    def test_messages_from_previous_run_are_discarded(self):
        sink = self.connect_pair()
        self.graph.start()
        previous = sink.received[0]
        self.graph.stop()
        self.graph.start()
        self.bus.publish("node/sink/in/in", previous.payload, schema=COMMAND, run_id=previous.run_id)
        self.assertEqual(len(sink.received), 1)
        self.assertNotEqual(previous.run_id, self.graph.run_id)

    def test_real_bus_initialization_and_worker_capture_timestamp(self):
        with Runtime() as runtime:
            register(runtime.registry)
            graph = runtime.graph
            graph.add_node("source", "test.once")
            graph.add_node("relay", "test.relay")
            sink = graph.add_node("sink", "test.sink").node_obj
            graph.connect("source", "out", "relay", "in")
            graph.connect("relay", "out", "sink", "in")
            graph.start()
            wait_until(lambda: sink.received)
            self.assertEqual(len(sink.received), 1)
            msg = sink.received[0]
            self.assertEqual(msg.timestamp.epoch_ns, 1250000000)
            self.assertEqual(msg.timestamp.source_id, "source")
            self.assertEqual(msg.published_timestamp.source_id, "relay")
            self.assertEqual(msg.clock_domain, "simulation")
            self.assertEqual(BusMessage.from_wire(msg.to_wire()), msg)
            # A worker exception is contained and visible, not a silent daemon exit.
            relay = graph.nodes["relay"].node_obj
            def broken(*args):
                raise RuntimeError("mapping worker failed")
            relay.process = broken
            graph.nodes["source"].node_obj.emit("out", {"linear": .1, "angular": 0., "time": 2.})
            wait_until(lambda: not graph.to_dict()["running"])
            self.assertEqual(relay.state, "failed")
            self.assertFalse(relay._thread.is_alive())
            self.assertIn("mapping worker failed", graph.failure_reason)

    def test_robot_configuration_renames_geometry_and_roundtrips(self):
        path = Path(__file__).resolve().parents[1]/"examples/four-wheel/navigation.pyrobot.json"
        document = ProjectDocument.model_validate_json(path.read_text())
        config = document.robot_config.model_copy(deep=True)
        xml = document.robot_urdf
        names = config.drive.left_joints + config.drive.right_joints
        for old, new in zip(names, ["left_a", "left_b", "right_a", "right_b"]):
            xml = xml.replace(old, new)
        xml = xml.replace("lidar_link", "scanner").replace("camera_link", "camera_mount")
        config.drive.left_joints, config.drive.right_joints = ["left_a", "left_b"], ["right_a", "right_b"]
        config.drive.lidar_frame, config.drive.camera_frame = "scanner", "camera_mount"
        config.environment.obstacles = []
        model = parse_urdf(xml)
        radius, track, mounts = robot_dimensions(model, config)
        self.assertAlmostEqual(track, .62)
        self.assertAlmostEqual(radius, .12)
        sim = FourWheelSimulator(radius, track, configuration=config)
        self.assertEqual(sim.scan(mounts["lidar_link"])["frame"], "scanner")
        self.assertEqual(len(sim.obstacles), 4)
        self.assertEqual(camera_image([0,0,0], obstacles=sim.obstacles).shape, (144,240,3))
        self.graph.robot_config = config
        exported = export_project(self.graph, self.graph.registry, "Custom", xml, {})
        candidate, _ = prepare_project(ProjectDocument.model_validate_json(exported.model_dump_json()), self.bus, self.graph.registry)
        try:
            self.assertEqual(candidate.robot_config, config)
        finally:
            candidate.close()
        with self.assertRaises(ValueError):
            RobotConfiguration.model_validate({"drive": {"type": "ackermann"}})


if __name__ == "__main__":
    unittest.main()
