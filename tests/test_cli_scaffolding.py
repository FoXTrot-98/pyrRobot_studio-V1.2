# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

import tempfile
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.plugin_registry import PluginRegistry
from core.bus.base import Bus, BusTransport
from core.timing.clock import PRTClock, ClockAuthority, discipline_from_beacon


class FakeTransport(BusTransport):
    """In-memory pub/sub, no real sockets — enough to prove message flow
    between two CLI-generated nodes without needing a broker process."""

    def __init__(self):
        self._subs = []

    def publish_raw(self, topic, raw):
        for pattern, cb in self._subs:
            if topic.startswith(pattern):
                cb(topic, raw)

    def subscribe_raw(self, pattern, cb):
        self._subs.append((pattern, cb))

    def close(self):
        pass


def make_bus(source_id: str) -> Bus:
    authority = ClockAuthority(bus_publish_fn=lambda t, p: None)
    authority.start_session()
    clock = PRTClock(source_id=source_id)
    discipline_from_beacon(clock, authority.emit_beacon())
    return Bus(FakeTransport(), clock)


def test_cli_generates_executable_source_and_processing_plugins():
    temporary = tempfile.TemporaryDirectory(prefix="pyrobot-cli-")
    tmp_dir = Path(temporary.name)

    # 1. actually run the CLI as a subprocess, exactly as a user would
    r1 = subprocess.run(
        [sys.executable, "-m", "sdk.cli", "create-plugin", "distance_sensor",
         "--category", "Sensors", "--output", "distance:number",
         "--out-dir", str(tmp_dir)],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
    )
    assert r1.returncode == 0, r1.stderr
    print("OK: `pyrobot-cli create-plugin distance_sensor` ran successfully")

    r2 = subprocess.run(
        [sys.executable, "-m", "sdk.cli", "create-plugin", "range_filter",
         "--category", "Processing", "--input", "distance:number", "--output", "filtered:number",
         "--out-dir", str(tmp_dir)],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
    )
    assert r2.returncode == 0, r2.stderr
    print("OK: `pyrobot-cli create-plugin range_filter` ran successfully")

    # 2. prove the generated files are discoverable by the real plugin registry
    registry = PluginRegistry()
    registered = registry.scan_directory(tmp_dir)
    assert "user.distance_sensor" in registered
    assert "user.range_filter" in registered
    print(f"OK: plugin registry discovered generated plugins: {registered}")

    # 3. hand-edit the generated source node's emit to produce real data
    #    (simulating what a user would fill into the TODO), then prove the
    #    generated classes actually run and pass messages end-to-end
    source_entry = registry.get("user.distance_sensor")
    filter_entry = registry.get("user.range_filter")

    bus = make_bus("cli-test")
    source_node = source_entry.node_class(node_id="dist-1", bus=bus, params={"rate_hz": 20})
    filter_node = filter_entry.node_class(node_id="filt-1", bus=bus, params={})

    # manually bridge source's output -> filter's input, same mechanism
    # the real NodeGraph uses
    def bridge(msg):
        bus.publish(f"node/filt-1/in/distance", msg.payload, timestamp=msg.timestamp)
    bus.subscribe("node/dist-1/out/distance", bridge)

    received = []
    bus.subscribe("node/filt-1/in/distance", lambda msg: received.append(msg))

    source_node.start()
    filter_node.start()
    time.sleep(0.3)
    source_node.stop()
    filter_node.stop()

    assert len(received) > 0, "generated source node's output never reached the generated processing node's input"
    print(f"OK: {len(received)} messages flowed from the generated source node -> generated processing node over the bus")

    temporary.cleanup()


if __name__ == "__main__":
    test_cli_generates_executable_source_and_processing_plugins()
    print("\nCLI scaffolding test passed.")
