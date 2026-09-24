"""
PRT — PyRobot Time
====================

A frame-accurate, multi-rate synchronization clock for PyRobot Studio.

Design goals (distinct from SMPTE, but inspired by it):
  - SMPTE ties everything to a fixed frame rate (24/25/30fps) with a
    drop-frame correction hack for NTSC. Robotics systems don't have
    one frame rate — a camera might run at 30Hz, a LiDAR at 10Hz, an
    IMU at 200Hz, all needing to resolve onto the same timeline.
  - PRT uses a single monotonic **epoch clock** (nanosecond resolution)
    as the ground truth, and expresses every stream's rate as a
    "tick group" relative to that epoch. Any two timestamps from any
    two streams are directly comparable and can be resampled/aligned
    without needing to know each other's native rate up front.
  - Still borrows SMPTE's idea of a broadcastable "time authority":
    one node on the bus is the clock source, and all others discipline
    to it (like genlock), so recordings taken on different machines
    still align to a common origin.

A PRTTimestamp is the atomic unit stamped onto every bus message at
the moment of capture (not at bus-receive), which avoids introducing
latency jitter into the recorded timeline.
"""

from __future__ import annotations

import time
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ClockRole(Enum):
    AUTHORITY = "authority"   # this process owns the epoch, broadcasts it
    DISCIPLINED = "disciplined"  # this process syncs to a remote authority
    FREE = "free"              # standalone / no sync (single-process dev mode)


@dataclass(frozen=True, slots=True)
class PRTTimestamp:
    """
    A single point in PyRobot Time.

    epoch_ns:      nanoseconds since the session's epoch (t=0 at session start,
                    NOT wall-clock unix time — this makes recordings portable
                    and diffable regardless of when they were captured).
    wall_ns:       unix wall-clock ns at capture, kept alongside epoch_ns for
                    human-readable logs/debugging only. Never used for sync math.
    sequence:      monotonically increasing counter *per source*, used to detect
                    drops/reordering independent of timestamp precision.
    source_id:     id of the node/device that stamped this (capture-time stamping).
    """
    epoch_ns: int
    wall_ns: int
    sequence: int
    source_id: str

    def as_seconds(self) -> float:
        return self.epoch_ns / 1e9

    def delta(self, other: "PRTTimestamp") -> float:
        """Signed difference in seconds: self - other."""
        return (self.epoch_ns - other.epoch_ns) / 1e9

    def frame_label(self, rate_hz: float) -> str:
        """
        Render as an SMPTE-like HH:MM:SS:FF label, but FF is relative to
        an arbitrary rate_hz (the stream's own rate), not a fixed broadcast
        rate. Two streams at different rates produce different FF ranges
        for the *same* epoch_ns — that's intentional, it's a display
        convenience, not the sync mechanism.
        """
        total_seconds = self.epoch_ns / 1e9
        hh = int(total_seconds // 3600)
        mm = int((total_seconds % 3600) // 60)
        ss = int(total_seconds % 60)
        ff = int((total_seconds - int(total_seconds)) * rate_hz)
        return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"

    def to_dict(self) -> dict:
        return {
            "epoch_ns": self.epoch_ns,
            "wall_ns": self.wall_ns,
            "sequence": self.sequence,
            "source_id": self.source_id,
        }

    @staticmethod
    def from_dict(d: dict) -> "PRTTimestamp":
        return PRTTimestamp(
            epoch_ns=d["epoch_ns"],
            wall_ns=d["wall_ns"],
            sequence=d["sequence"],
            source_id=d["source_id"],
        )


class PRTClock:
    """
    Per-source clock handle. One of these lives inside every plugin/device
    node. It knows the session epoch (set by the ClockAuthority at session
    start, or received via discipline messages if this node isn't the
    authority) and stamps outgoing messages.

    Thread-safe: capture callbacks from device drivers often run on their
    own thread.
    """

    def __init__(self, source_id: Optional[str] = None):
        self.source_id = source_id or f"src-{uuid.uuid4().hex[:8]}"
        self._epoch_origin_ns: Optional[int] = None  # wall_ns at epoch t=0
        self._monotonic_origin_ns = None
        self._lock = threading.Lock()
        self._sequence = 0
        self._offset_ns = 0  # discipline correction applied to local clock
        self.role: ClockRole = ClockRole.FREE

    # -- epoch management -------------------------------------------------

    def set_epoch_origin(self, wall_ns: int) -> None:
        """Called once by the ClockAuthority, or when a DISCIPLINED node
        receives its first sync broadcast from the authority."""
        with self._lock:
            self._epoch_origin_ns = wall_ns
            self._monotonic_origin_ns = time.monotonic_ns() - (time.time_ns() - wall_ns)

    def apply_discipline_offset(self, offset_ns: int) -> None:
        """Adjust local->authority skew, from periodic sync broadcasts."""
        with self._lock:
            self._offset_ns = offset_ns

    @property
    def has_epoch(self) -> bool:
        return self._epoch_origin_ns is not None

    # -- stamping -----------------------------------------------------------

    def now(self) -> PRTTimestamp:
        """Stamp the current instant. Call this at the moment of capture,
        e.g. immediately after a frame grab or sensor read — not after
        the data has been queued or serialized."""
        if self._epoch_origin_ns is None:
            raise RuntimeError(
                f"PRTClock[{self.source_id}] has no epoch set yet — "
                f"node must receive a session start / discipline broadcast "
                f"before it can stamp messages."
            )
        wall_ns = time.time_ns()
        with self._lock:
            epoch_ns = time.monotonic_ns() - self._monotonic_origin_ns + self._offset_ns
            self._sequence += 1
            seq = self._sequence
        return PRTTimestamp(
            epoch_ns=epoch_ns,
            wall_ns=wall_ns,
            sequence=seq,
            source_id=self.source_id,
        )


class ClockAuthority:
    """
    Lives in exactly one place per session (usually the backend server
    process). Defines t=0 for the session and periodically broadcasts
    a sync beacon over the bus so DISCIPLINED clocks can correct drift.

    Broadcast payload is intentionally tiny (topic: 'prt/sync') so it can
    go out at high frequency (e.g. 4-10 Hz) without bus load concerns.
    """

    SYNC_TOPIC = "prt/sync"

    def __init__(self, bus_publish_fn):
        """
        bus_publish_fn: callable(topic: str, payload: dict) -> None
                         injected so this module has zero direct dependency
                         on the LCM/ZeroMQ bus implementation.
        """
        self._publish = bus_publish_fn
        self.epoch_origin_wall_ns = time.time_ns()
        self._beacon_seq = 0

    def start_session(self) -> int:
        """Call once when a new recording/live session begins."""
        self.epoch_origin_wall_ns = time.time_ns()
        self._beacon_seq = 0
        return self.epoch_origin_wall_ns

    def emit_beacon(self) -> dict:
        """Call periodically (e.g. from a timer/asyncio task) to broadcast
        the authority's current time so disciplined nodes can correct drift."""
        self._beacon_seq += 1
        payload = {
            "epoch_origin_wall_ns": self.epoch_origin_wall_ns,
            "authority_wall_ns": time.time_ns(),
            "beacon_seq": self._beacon_seq,
        }
        self._publish(self.SYNC_TOPIC, payload)
        return payload


def discipline_from_beacon(clock: PRTClock, beacon_payload: dict) -> None:
    """
    Apply a received sync beacon to a DISCIPLINED clock.
    Simple offset correction (no PLL/filtering yet — sufficient for LAN-local
    sync; a smoothing filter can be layered in later if jitter becomes an
    issue over WiFi-connected devices).
    """
    clock.role = ClockRole.DISCIPLINED
    if not clock.has_epoch:
        clock.set_epoch_origin(beacon_payload["epoch_origin_wall_ns"])
    local_wall_ns = time.time_ns()
    authority_wall_ns = beacon_payload["authority_wall_ns"]
    offset = authority_wall_ns - local_wall_ns
    clock.apply_discipline_offset(offset)
