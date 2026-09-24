import sys
import time
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.bus.broker import run_broker, FRONTEND_ENDPOINT, BACKEND_ENDPOINT
from core.bus.base import Bus, ZmqTransport
from core.timing.clock import PRTClock, ClockAuthority, discipline_from_beacon
from plugins.examples.fake_imu import FakeImuNode


def test_end_to_end_plugin_over_real_bus():
    # 1. start broker in background
    broker_thread = threading.Thread(target=run_broker, daemon=True)
    broker_thread.start()
    time.sleep(0.3)  # let broker bind

    # 2. set up a PRT clock (single-process "authority" for this test)
    authority = ClockAuthority(bus_publish_fn=lambda t, p: None)
    authority.start_session()
    clock = PRTClock(source_id="fake-imu-node")
    discipline_from_beacon(clock, authority.emit_beacon())

    # 3. wire up the bus and the plugin node
    transport = ZmqTransport(FRONTEND_ENDPOINT, BACKEND_ENDPOINT)
    bus = Bus(transport, clock)
    node = FakeImuNode(node_id="imu-1", bus=bus, params={"rate_hz": 100}, urdf_link="imu_link")

    # node.start() subscribes to its (empty) inputs and calls on_start(),
    # which spins up the publishing thread
    node.start()

    # 4. a plain subscriber, simulating the Studio UI / another node
    received = []
    sub_transport = ZmqTransport(FRONTEND_ENDPOINT, BACKEND_ENDPOINT)
    sub_clock = PRTClock(source_id="test-subscriber")
    sub_bus = Bus(sub_transport, sub_clock)
    sub_bus.subscribe("node/imu-1/out/imu", lambda msg: received.append(msg))

    time.sleep(0.5)  # let messages flow
    node.stop()

    assert len(received) > 10, f"expected >10 IMU messages in 0.5s at 100Hz, got {len(received)}"
    first = received[0]
    assert first.topic == "node/imu-1/out/imu"
    assert "accel" in first.payload
    assert first.payload["frame"] == "imu_link"
    assert first.timestamp.source_id == "imu-1"
    assert first.published_timestamp.source_id == "imu-1"

    # timestamps should be monotonically increasing and PRT-correct
    for a, b in zip(received, received[1:]):
        assert b.timestamp.epoch_ns >= a.timestamp.epoch_ns
        assert b.timestamp.sequence == a.timestamp.sequence + 1

    print(f"OK: received {len(received)} correctly-stamped IMU messages over the real bus in 0.5s")
    print(f"    first payload: {first.payload}")
    print(f"    first timestamp: epoch_ns={first.timestamp.epoch_ns} seq={first.timestamp.sequence} frame_label={first.timestamp.frame_label(100)}")


if __name__ == "__main__":
    test_end_to_end_plugin_over_real_bus()
    print("\nBus integration test passed.")
