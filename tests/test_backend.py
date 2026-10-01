# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from backend.app.main import app

FIXTURE = Path(__file__).parent / "fixtures" / "sample_robot.urdf"


def test_backend_full_flow():
    with TestClient(app) as client:
        with FIXTURE.open("rb") as robot:
            assert client.post("/api/robot/urdf", files={"file": ("robot.urdf", robot)}).status_code == 200
        # 1. plugin discovery
        r = client.get("/api/plugins")
        assert r.status_code == 200
        plugins = r.json()["plugins"]
        plugin_ids = [p["id"] for p in plugins]
        assert "pyrobot.examples.fake_imu" in plugin_ids
        print(f"OK: /api/plugins discovered {len(plugins)} plugin(s): {plugin_ids}")

        # 2. URDF upload
        with open(FIXTURE, "rb") as f:
            r = client.post("/api/robot/urdf", files={"file": ("sample_robot.urdf", f, "application/xml")})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["name"] == "sample_bot"
        assert "lidar_link" in body["links"]
        print(f"OK: /api/robot/urdf parsed '{body['name']}' with links {body['links']}")

        r = client.get("/api/robot/links")
        assert r.status_code == 200
        assert "lidar_link" in r.json()["links"]
        print("OK: /api/robot/links returns the loaded robot's links")

        # 3. reject a node that requires a urdf_link binding without one
        r = client.post("/api/graph/nodes", json={
            "node_id": "imu-1", "plugin_id": "pyrobot.examples.fake_imu", "params": {"rate_hz": 200},
        })
        assert r.status_code == 400, "expected rejection: fake_imu requires_urdf_link"
        print("OK: adding a URDF-required node without a link binding correctly rejected (400)")

        # 4. add node WITH a urdf_link binding
        r = client.post("/api/graph/nodes", json={
            "node_id": "imu-1", "plugin_id": "pyrobot.examples.fake_imu",
            "params": {"rate_hz": 200}, "urdf_link": "lidar_link",
        })
        assert r.status_code == 200, r.text
        graph_state = r.json()
        assert len(graph_state["nodes"]) == 1
        print("OK: added node 'imu-1' bound to URDF link 'lidar_link'")

        # 5. reject unknown plugin id
        r = client.post("/api/graph/nodes", json={"node_id": "bad-1", "plugin_id": "nonexistent.plugin"})
        assert r.status_code == 404
        print("OK: unknown plugin id correctly rejected (404)")

        # 6. start the graph and verify live messages flow over the websocket
        r = client.post("/api/graph/start")
        assert r.status_code == 200
        assert r.json()["running"] is True
        print("OK: graph started")

        received = []
        with client.websocket_connect("/ws/bus") as ws:
            deadline = time.time() + 1.5
            while time.time() < deadline and len(received) < 5:
                msg = ws.receive_text()
                import json as _json
                received.append(_json.loads(msg))

        assert len(received) >= 5, f"expected >=5 live messages over /ws/bus, got {len(received)}"
        assert received[0]["topic"] == "node/imu-1/out/imu"
        assert received[0]["payload"]["frame"] == "lidar_link"
        print(f"OK: /ws/bus streamed {len(received)} live messages; first payload frame='{received[0]['payload']['frame']}'")

        r = client.post("/api/graph/stop")
        assert r.status_code == 200
        assert r.json()["running"] is False
        print("OK: graph stopped")

        # 7. remove node
        r = client.delete("/api/graph/nodes/imu-1")
        assert r.status_code == 200
        assert len(r.json()["nodes"]) == 0
        print("OK: node removed from graph")


def test_node_to_node_connection():
    with TestClient(app) as client:
        with FIXTURE.open("rb") as robot:
            assert client.post("/api/robot/urdf", files={"file": ("robot.urdf", robot)}).status_code == 200
        client.post("/api/graph/nodes", json={
            "node_id": "imu-1", "plugin_id": "pyrobot.examples.fake_imu",
            "params": {"rate_hz": 200}, "urdf_link": "base_link",
        })
        client.post("/api/graph/nodes", json={
            "node_id": "logger-1", "plugin_id": "pyrobot.examples.logger",
        })

        # reject connecting to a nonexistent port
        r = client.post("/api/graph/connections", json={
            "from_node": "imu-1", "from_port": "nope", "to_node": "logger-1", "to_port": "in",
        })
        assert r.status_code == 400
        print("OK: connecting from a nonexistent output port correctly rejected (400)")

        r = client.post("/api/graph/connections", json={
            "from_node": "imu-1", "from_port": "imu", "to_node": "logger-1", "to_port": "in",
        })
        assert r.status_code == 200, r.text
        assert len(r.json()["connections"]) == 1
        print("OK: connected imu-1.imu -> logger-1.in")

        client.post("/api/graph/start")

        received = []
        with client.websocket_connect("/ws/bus") as ws:
            deadline = time.time() + 1.0
            while time.time() < deadline and len(received) < 10:
                import json as _json
                received.append(_json.loads(ws.receive_text()))

        client.post("/api/graph/stop")

        # the bridged message on logger-1's INPUT topic proves the graph
        # actually routed imu-1's output into logger-1, not just that
        # imu-1 is publishing on its own
        bridged = [m for m in received if m["topic"] == "node/logger-1/in/in"]
        assert len(bridged) > 0, f"expected bridged messages on node/logger-1/in/in, got topics: {set(m['topic'] for m in received)}"
        assert bridged[0]["payload"]["frame"] == "base_link"
        print(f"OK: {len(bridged)} messages bridged from imu-1's output onto logger-1's input port (graph connection works)")


def test_live_param_update_changes_behavior():
    with TestClient(app) as client:
        with FIXTURE.open("rb") as robot:
            assert client.post("/api/robot/urdf", files={"file": ("robot.urdf", robot)}).status_code == 200
        client.post("/api/graph/nodes", json={
            "node_id": "imu-rate-test", "plugin_id": "pyrobot.examples.fake_imu",
            "params": {"rate_hz": 20}, "urdf_link": "base_link",
        })
        client.post("/api/graph/start")

        def count_messages_over(seconds: float, preview=False) -> int:
            count = 0
            with client.websocket_connect("/ws/bus?preview=true" if preview else "/ws/bus") as ws:
                deadline = time.time() + seconds
                while time.time() < deadline:
                    import json as _json
                    msg = _json.loads(ws.receive_text())
                    if msg["topic"] == "node/imu-rate-test/out/imu":
                        count += 1
            return count

        slow_count = count_messages_over(0.5)
        print(f"OK: at rate_hz=20, received ~{slow_count} messages in 0.5s (expect ~10)")
        assert 4 <= slow_count <= 16, f"unexpected count at 20Hz: {slow_count}"

        r = client.patch("/api/graph/nodes/imu-rate-test/params", json={"params": {"not_a_real_param": 1}})
        assert r.status_code == 400
        print("OK: updating an undeclared param key correctly rejected (400)")

        r = client.patch("/api/graph/nodes/imu-rate-test/params", json={"params": {"rate_hz": 200}})
        assert r.status_code == 200, r.text
        print("OK: PATCH /api/graph/nodes/imu-rate-test/params accepted rate_hz=200")

        fast_count = count_messages_over(0.5)
        print(f"OK: after live update to rate_hz=200, received ~{fast_count} messages in 0.5s (expect ~100)")
        assert fast_count > slow_count * 3, (
            f"expected a real behavior change after live param update, got {slow_count} -> {fast_count}"
        )
        preview_count = count_messages_over(.5, preview=True)
        assert 1 <= preview_count <= 7, f"preview did not coalesce high-rate updates: {preview_count}"

        client.post("/api/graph/stop")
        client.delete("/api/graph/nodes/imu-rate-test")
        print("OK: live param update measurably changed running node behavior (not just the stored dict)")


if __name__ == "__main__":
    test_backend_full_flow()
    test_node_to_node_connection()
    test_live_param_update_changes_behavior()
    print("\nBackend integration test passed.")
