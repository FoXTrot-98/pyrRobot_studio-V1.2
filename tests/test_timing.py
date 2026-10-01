# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.timing.clock import PRTClock, ClockAuthority, discipline_from_beacon
from core.timing.timeline import TimelineRecorder, TimelinePlayer


def test_clock_requires_epoch_before_stamping():
    clock = PRTClock(source_id="test-cam")
    try:
        clock.now()
        assert False, "expected RuntimeError before epoch is set"
    except RuntimeError:
        pass
    print("OK: clock refuses to stamp before epoch set")


def test_authority_and_discipline():
    beacons = []
    authority = ClockAuthority(bus_publish_fn=lambda topic, payload: beacons.append((topic, payload)))
    authority.start_session()
    beacon_payload = authority.emit_beacon()

    follower = PRTClock(source_id="follower-1")
    discipline_from_beacon(follower, beacon_payload)
    assert follower.has_epoch

    ts1 = follower.now()
    time.sleep(0.01)
    ts2 = follower.now()
    assert ts2.epoch_ns > ts1.epoch_ns
    assert ts2.sequence == ts1.sequence + 1
    assert ts2.delta(ts1) > 0
    print(f"OK: disciplined clock stamps monotonically increasing timestamps ({ts1.epoch_ns} -> {ts2.epoch_ns})")


def test_frame_label():
    authority = ClockAuthority(bus_publish_fn=lambda t, p: None)
    authority.start_session()
    clock = PRTClock(source_id="cam")
    discipline_from_beacon(clock, authority.emit_beacon())
    ts = clock.now()
    label = ts.frame_label(rate_hz=30.0)
    assert len(label.split(":")) == 4
    print(f"OK: frame label renders as {label}")


def test_timeline_record_and_playback(tmp_path=None):
    import tempfile
    temporary = tempfile.TemporaryDirectory(prefix="pyrobot-timing-") if tmp_path is None else None
    tmp_path = Path(temporary.name) if temporary else tmp_path

    authority = ClockAuthority(bus_publish_fn=lambda t, p: None)
    authority.start_session()
    clock = PRTClock(source_id="cam-1")
    discipline_from_beacon(clock, authority.emit_beacon())

    recorder = TimelineRecorder(tmp_path)
    written_entries = []
    for i in range(5):
        ts = clock.now()
        payload = f"frame-{i}".encode("utf-8")
        recorder.write(ts, "camera/frame", payload)
        written_entries.append((ts, payload))
        time.sleep(0.005)
    recorder.close()

    player = TimelinePlayer(tmp_path)
    assert player.duration_ns() >= written_entries[-1][0].epoch_ns
    entries = list(player.entries_between(0, player.duration_ns() + 1))
    assert len(entries) == 5
    for entry, (orig_ts, orig_payload) in zip(entries, written_entries):
        assert entry.epoch_ns == orig_ts.epoch_ns
        assert player.read_payload(entry) == orig_payload
    print(f"OK: recorded and read back {len(entries)} entries with matching payloads")

    received = []
    player2 = TimelinePlayer(tmp_path)
    player2.play(lambda e, payload: received.append(payload), speed=0, blocking=True)
    assert len(received) == 5
    assert received[0] == b"frame-0"
    print("OK: playback replayed all 5 entries in order")
    player.close()
    player2.close()
    if temporary:
        temporary.cleanup()


if __name__ == "__main__":
    test_clock_requires_epoch_before_stamping()
    test_authority_and_discipline()
    test_frame_label()
    test_timeline_record_and_playback()
    print("\nAll timing tests passed.")
