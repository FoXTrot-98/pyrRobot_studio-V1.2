"""Regression tests for lifecycle, graph validation and project round trips."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.bus.base import Bus, BusTransport, Subscription
from core.timing.clock import PRTClock
from sdk.pyrobot_plugin import Node, PluginManifest, PortSpec, PortDataType, ParamSpec
from backend.app.graph import NodeGraph, GraphError
from backend.app.plugin_registry import PluginRegistry, PluginEntry
from backend.app.project import ProjectDocument, prepare_project, export_project


class MemoryTransport(BusTransport):
    def __init__(self):
        self.callbacks = {}

    def subscribe_raw(self, pattern, callback):
        token = object()
        self.callbacks[token] = (pattern, callback)
        return Subscription(lambda: self.callbacks.pop(token, None))

    def publish_raw(self, topic, raw):
        for pattern, callback in list(self.callbacks.values()):
            if topic.startswith(pattern):
                callback(topic, raw)

    def close(self):
        self.callbacks.clear()


class Source(Node):
    manifest = PluginManifest(id="test.source", name="Source", category="Test",
        outputs=[PortSpec("out", PortDataType.NUMBER)],
        params=[ParamSpec("rate", "number", default=10, min=1, max=100)])


class Sink(Node):
    manifest = PluginManifest(id="test.sink", name="Sink", category="Test",
        inputs=[PortSpec("in", PortDataType.NUMBER)])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.received = []

    def on_message(self, port, message):
        self.received.append(message.payload)


class Broken(Source):
    manifest = PluginManifest(id="test.broken", name="Broken", category="Test")

    def on_start(self):
        raise RuntimeError("driver unavailable")


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.transport = MemoryTransport()
        clock = PRTClock("test")
        clock.set_epoch_origin(0)
        self.bus = Bus(self.transport, clock)
        self.registry = PluginRegistry()
        for cls in (Source, Sink, Broken):
            self.registry._entries[cls.manifest.id] = PluginEntry(cls.manifest, cls, Path(__file__))
        self.graph = NodeGraph(self.bus, self.registry)
        self.source = self.graph.add_node("source", "test.source").node_obj
        self.sink = self.graph.add_node("sink", "test.sink").node_obj
        self.graph.connect("source", "out", "sink", "in")

    def tearDown(self):
        self.graph.close()
        self.bus.close()

    def test_repeated_start_and_restart_deliver_once(self):
        for _ in range(3):
            self.graph.start()
            self.graph.start()
            self.source.emit("out", {"value": 1})
            self.graph.stop()
            self.source.emit("out", {"value": 2})
        self.assertEqual(self.sink.received, [{"value": 1}] * 3)
        self.assertEqual(len(self.transport.callbacks), 1)  # only the bridge remains

    def test_disconnect_and_remove_release_subscriptions(self):
        self.graph.start()
        self.graph.disconnect("source", "out", "sink", "in")
        self.source.emit("out", {"value": 1})
        self.assertEqual(self.sink.received, [])
        self.graph.connect("source", "out", "sink", "in")
        self.graph.remove_node("sink")
        self.assertEqual(len(self.transport.callbacks), 0)

    def test_exact_topics_do_not_match_port_prefix(self):
        self.graph.start()
        self.bus.publish("node/source/out/out-extra", {"value": 1})
        self.assertEqual(self.sink.received, [])

    def test_invalid_parameters_leave_previous_values(self):
        for value in (0, 101, True, "fast", float("nan")):
            with self.assertRaises(GraphError):
                self.graph.update_node_params("source", {"rate": value})
        self.assertEqual(self.source.params["rate"], 10)

    def test_stopped_parameter_edits_do_not_start_workers(self):
        self.graph.update_node_params("source", {"rate": 20})
        self.assertEqual(self.source.state, "stopped")
        self.assertFalse(self.source._running)

    def test_failed_start_rolls_back_other_nodes(self):
        self.graph.add_node("broken", "test.broken")
        with self.assertRaises(GraphError):
            self.graph.start()
        self.assertFalse(self.graph.to_dict()["running"])
        self.assertFalse(self.sink._running)
        self.assertFalse(self.source._running)
        self.assertEqual(len(self.transport.callbacks), 1)

    def test_incompatible_ports_rejected(self):
        class ImageSink(Sink):
            manifest = PluginManifest(id="test.image", name="Image", category="Test",
                inputs=[PortSpec("in", PortDataType.IMAGE)])
        self.registry._entries["test.image"] = PluginEntry(ImageSink.manifest, ImageSink, Path(__file__))
        self.graph.add_node("image", "test.image")
        with self.assertRaises(GraphError):
            self.graph.connect("source", "out", "image", "in")

    def test_serial_loopback_reads_and_stops(self):
        import serial
        import time
        from plugins.devices.serial_reader import SerialReaderNode
        port = serial.serial_for_url("loop://", timeout=.1)
        received = []
        handle = self.bus.subscribe("node/serial/out/line", lambda msg: received.append(msg.payload))
        node = SerialReaderNode(node_id="serial", bus=self.bus, params={"port": "loop://"})
        try:
            with patch("serial.Serial", return_value=port):
                node.start()
            port.write(b"robot-ready\n")
            deadline = time.monotonic() + 2
            while not received and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(received[0]["text"], "robot-ready")
        finally:
            node.stop()
            handle.close()
        self.assertFalse(node._thread.is_alive())

    def test_failed_device_start_rolls_back_graph(self):
        from plugins.devices.serial_reader import SerialReaderNode
        manifest = SerialReaderNode.manifest
        self.registry._entries[manifest.id] = PluginEntry(manifest, SerialReaderNode, Path(__file__))
        self.graph.add_node("serial", manifest.id)
        with patch("serial.Serial", side_effect=OSError("disconnected")):
            with self.assertRaises(GraphError):
                self.graph.start()
        self.assertFalse(self.source._running)
        self.assertEqual(self.graph.nodes["serial"].node_obj.state, "failed")

    def test_can_writer_open_failure_is_not_reported_running(self):
        from plugins.devices.can_writer import CanBusWriterNode
        node = CanBusWriterNode(node_id="can", bus=self.bus)
        with patch("can.interface.Bus", side_effect=OSError("unavailable")):
            with self.assertRaises(RuntimeError):
                node.start()
        self.assertEqual(node.state, "failed")
        self.assertFalse(node._running)

    def test_camera_requires_explicit_synthetic_opt_in(self):
        from plugins.devices.camera_source import CameraSourceNode
        node = CameraSourceNode(node_id="camera", bus=self.bus, urdf_link="base_link")
        with patch("cv2.VideoCapture") as capture:
            capture.return_value.isOpened.return_value = False
            with self.assertRaises(RuntimeError):
                node.start()
        self.assertEqual(node.state, "failed")

    def test_project_roundtrip_and_failed_candidate_cleanup(self):
        doc = export_project(self.graph, self.registry, "Robot", None, {"source": {"x": 42, "y": 21}})
        parsed = ProjectDocument.model_validate_json(doc.model_dump_json())
        candidate, _ = prepare_project(parsed, self.bus, self.registry)
        try:
            self.assertEqual(candidate.to_dict(), self.graph.to_dict())
            self.assertEqual(parsed.positions["source"].x, 42)
        finally:
            candidate.close()
        count = len(self.transport.callbacks)
        invalid = doc.model_copy(deep=True)
        invalid.connections.append(invalid.connections[0])
        with self.assertRaises(GraphError):
            prepare_project(invalid, self.bus, self.registry)
        self.assertEqual(len(self.transport.callbacks), count)


class ProjectApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from backend.app import main
        self.main = main
        self.rerun = patch.object(main, "init_rerun")
        self.rerun.start()
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()
        xml = (Path(__file__).parent / "fixtures/sample_robot.urdf").read_text()
        self.assertEqual(self.client.post("/api/robot/urdf", files={"file": ("robot.urdf", xml)}).status_code, 200)
        response = self.client.post("/api/graph/nodes", json={
            "node_id": "imu", "plugin_id": "pyrobot.examples.fake_imu", "urdf_link": "lidar_link"})
        self.assertEqual(response.status_code, 200, response.text)

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.rerun.stop()

    def export(self):
        response = self.client.post("/api/project/export", json={"name": "My robot", "positions": {"imu": {"x": 120, "y": 50}}})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_export_import_preserves_robot_params_binding_layout(self):
        self.assertEqual(self.client.patch("/api/graph/nodes/imu/params", json={"params": {"rate_hz": 42}}).status_code, 200)
        document = self.export()
        self.assertIn("<robot", document["robot_urdf"])
        self.client.delete("/api/graph/nodes/imu")
        response = self.client.post("/api/project/import", json=document)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["positions"]["imu"]["x"], 120)
        state = self.client.get("/api/graph").json()
        self.assertFalse(state["running"])
        self.assertEqual(state["nodes"][0]["params"]["rate_hz"], 42)
        self.assertEqual(state["nodes"][0]["urdf_link"], "lidar_link")

    def test_invalid_import_preserves_existing_project(self):
        original = self.export()
        for mutation in ("plugin", "version", "link", "schema", "port", "xml"):
            document = copy.deepcopy(original)
            if mutation == "plugin": document["nodes"][0]["plugin_id"] = "missing"
            if mutation == "version": document["nodes"][0]["plugin_version"] = "99"
            if mutation == "link": document["nodes"][0]["urdf_link"] = "missing"
            if mutation == "schema": document["schema_version"] = 999
            if mutation == "xml": document["robot_urdf"] = "invalid"
            if mutation == "port": document["connections"] = [{"from_node": "imu", "from_port": "missing", "to_node": "imu", "to_port": "missing"}]
            self.assertIn(self.client.post("/api/project/import", json=document).status_code, (400, 422))
            self.assertEqual(self.export(), original)

    def test_running_project_cannot_be_replaced(self):
        document = self.export()
        self.assertEqual(self.client.post("/api/graph/start").status_code, 200)
        self.assertEqual(self.client.post("/api/project/import", json=document).status_code, 409)
        self.assertTrue(self.client.get("/api/graph").json()["running"])

    def test_binding_validation(self):
        self.assertEqual(self.client.patch("/api/graph/nodes/imu/binding", json={"urdf_link": "missing"}).status_code, 400)
        self.assertEqual(self.client.patch("/api/graph/nodes/imu/binding", json={"urdf_link": "base_link"}).status_code, 200)

    def test_idle_websocket_disconnect_unsubscribes(self):
        transport = self.main.runtime.bus._transport
        before = len(transport._callbacks)
        with self.client.websocket_connect("/ws/bus"):
            self.assertEqual(len(transport._callbacks), before + 1)
        import time
        deadline = time.monotonic() + 2
        while len(transport._callbacks) != before and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(len(transport._callbacks), before)


if __name__ == "__main__":
    unittest.main()
