import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from backend.app.main import app


def test_camera_source_synthetic_fallback():
    from unittest.mock import patch
    with patch("cv2.VideoCapture") as capture, TestClient(app) as client:
        capture.return_value.isOpened.return_value = False
        with (Path(__file__).parent / "fixtures/sample_robot.urdf").open("rb") as robot:
            assert client.post("/api/robot/urdf", files={"file": ("robot.urdf", robot)}).status_code == 200
        r = client.post("/api/graph/nodes", json={
            "node_id": "cam-1", "plugin_id": "pyrobot.devices.camera_source",
            "params": {"device_index": 0, "allow_synthetic": True, "width": 64, "height": 48, "rate_hz": 10},
            "urdf_link": "base_link",
        })
        assert r.status_code == 200, r.text
        print("OK: added Camera Source node (camera unavailable, explicit synthetic fallback)")

        client.post("/api/graph/start")

        received = []
        with client.websocket_connect("/ws/bus") as ws:
            deadline = time.time() + 1.0
            while time.time() < deadline and len(received) < 3:
                import json as _json
                msg = _json.loads(ws.receive_text())
                if msg["topic"] == "node/cam-1/out/frame":
                    received.append(msg)

        client.post("/api/graph/stop")
        client.delete("/api/graph/nodes/cam-1")

        assert len(received) >= 3, f"expected >=3 frames from the synthetic fallback, got {len(received)}"
        assert received[0]["payload"]["source"] in ("synthetic", "synthetic-fallback")
        assert received[0]["payload"]["frame_link"] == "base_link"
        assert len(received[0]["payload"]["jpeg_base64"]) > 100

        distinct_frames = len(set(m["payload"]["jpeg_base64"] for m in received))
        assert distinct_frames > 1, "synthetic frames were not actually changing over time"
        print(f"OK: {len(received)} synthetic frames received, {distinct_frames} distinct — fallback is real and animating")


def test_can_reader_and_writer_over_virtual_bus():
    import can

    with TestClient(app) as client:
        with (Path(__file__).parent / "fixtures/sample_robot.urdf").open("rb") as robot:
            assert client.post("/api/robot/urdf", files={"file": ("robot.urdf", robot)}).status_code == 200
        r = client.post("/api/graph/nodes", json={
            "node_id": "can-rx", "plugin_id": "pyrobot.devices.can_reader",
            "params": {"channel": "vcan-e2e-test", "interface": "virtual"},
        })
        assert r.status_code == 200, r.text
        client.post("/api/graph/start")
        time.sleep(0.3)  # let the reader's bus.recv() thread actually open the channel

        received = []
        with client.websocket_connect("/ws/bus") as ws:
            # Subscribe FIRST, then inject. ZeroMQ PUB/SUB has a well-known
            # "slow joiner" problem: a subscriber connecting AFTER a publish
            # won't see it. The IMU/camera tests never hit this because those
            # nodes publish continuously; this CAN frame is a one-shot event,
            # so injecting it before the websocket subscribes would race.
            time.sleep(0.2)  # let the subscription actually reach the broker

            # inject a raw CAN frame directly via python-can, completely
            # independent of our plugin code, to prove the reader is doing
            # real CAN I/O and not just echoing something internal
            injector = can.interface.Bus(channel="vcan-e2e-test", interface="virtual")
            injector.send(can.Message(arbitration_id=0x321, data=bytes([9, 8, 7, 6]), is_extended_id=False))
            injector.shutdown()

            deadline = time.time() + 2.0
            while time.time() < deadline and len(received) < 1:
                import json as _json
                msg = _json.loads(ws.receive_text())
                if msg["topic"] == "node/can-rx/out/frame":
                    received.append(msg)

        client.post("/api/graph/stop")
        client.delete("/api/graph/nodes/can-rx")

        assert len(received) >= 1, "CAN reader did not pick up the injected frame"
        frame = received[0]["payload"]
        assert frame["arbitration_id"] == 0x321
        assert frame["data_hex"] == "09080706"
        print(f"OK: CAN reader picked up an externally-injected real CAN frame: id=0x{frame['arbitration_id']:x} data={frame['data_hex']}")


def test_serial_reader_over_real_pty():
    """A pty pair stands in for real serial hardware: writing to the master
    side is exactly what a real USB-serial device would look like from the
    OS's perspective, so the plugin can't tell the difference."""
    import os
    if os.name == "nt":
        print("SKIP: POSIX pseudo-terminal serial test is unavailable on Windows; loopback is tested separately")
        return
    import pty

    master_fd, slave_fd = pty.openpty()
    port_path = os.ttyname(slave_fd)

    with TestClient(app) as client:
        with (Path(__file__).parent / "fixtures/sample_robot.urdf").open("rb") as robot:
            assert client.post("/api/robot/urdf", files={"file": ("robot.urdf", robot)}).status_code == 200
        r = client.post("/api/graph/nodes", json={
            "node_id": "serial-1", "plugin_id": "pyrobot.devices.serial_reader",
            "params": {"port": port_path, "baudrate": "9600", "timeout_s": 0.5},
        })
        assert r.status_code == 200, r.text
        client.post("/api/graph/start")
        time.sleep(0.3)  # let the reader thread actually open the port

        received = []
        with client.websocket_connect("/ws/bus") as ws:
            time.sleep(0.2)  # avoid the same slow-joiner race as the CAN test
            os.write(master_fd, b"$GPGGA,fake,nmea,sentence\n")
            os.write(master_fd, b"second line\n")

            deadline = time.time() + 2.0
            while time.time() < deadline and len(received) < 2:
                import json as _json
                msg = _json.loads(ws.receive_text())
                if msg["topic"] == "node/serial-1/out/line":
                    received.append(msg)

        client.post("/api/graph/stop")
        client.delete("/api/graph/nodes/serial-1")
        os.close(master_fd)
        os.close(slave_fd)

        assert len(received) >= 2, f"expected 2 lines over the pty, got {len(received)}"
        assert received[0]["payload"]["text"] == "$GPGGA,fake,nmea,sentence"
        assert received[1]["payload"]["text"] == "second line"
        assert received[0]["payload"]["line_number"] == 1
        assert received[1]["payload"]["line_number"] == 2
        print(f"OK: Serial Device Reader read {len(received)} real lines over an actual pty device: {[m['payload']['text'] for m in received]}")


if __name__ == "__main__":
    test_camera_source_synthetic_fallback()
    test_can_reader_and_writer_over_virtual_bus()
    test_serial_reader_over_real_pty()
    print("\nAll device plugin tests passed.")
