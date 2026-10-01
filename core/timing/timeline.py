# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""
PRT Timeline — recording, seeking, and replay.

Every message that crosses the bus during a recording session is logged
as a (PRTTimestamp, topic, payload) triple. Because timestamps are epoch-
relative (see clock.py), a recorded session replays deterministically
regardless of the machine or wall-clock time it's played back on.

Storage: messages are written to a per-topic Rerun recording (.rrd) where
the payload is a visualizable type (images, point clouds, poses), AND to a
lightweight sidecar index (.prt_index, sqlite) that stores just
(epoch_ns, sequence, source_id, topic, byte_offset) for every message —
this index is what makes seeking/scrubbing fast without needing Rerun to
scan its whole log for non-visual data (e.g. control commands, plugin
params) that doesn't belong in the 3D viewer.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional

from .clock import PRTTimestamp


@dataclass
class TimelineEntry:
    epoch_ns: int
    sequence: int
    source_id: str
    topic: str
    byte_offset: int
    byte_length: int


class TimelineRecorder:
    """Writes the seek index while a session is being captured. Actual
    payload bytes are appended to a flat .prtlog file; Rerun logging for
    visual topics happens in parallel via the Rerun SDK (kept separate so
    this index works for ALL topics, visual or not)."""

    def __init__(self, session_dir: Path):
        self.session_dir = session_dir
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.session_dir / "session.prt_index"
        self._log_path = self.session_dir / "session.prtlog"
        self._db = sqlite3.connect(self._index_path, check_same_thread=False)
        self._log_file = open(self._log_path, "ab")
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS entries (
                epoch_ns INTEGER NOT NULL,
                sequence INTEGER NOT NULL,
                source_id TEXT NOT NULL,
                topic TEXT NOT NULL,
                byte_offset INTEGER NOT NULL,
                byte_length INTEGER NOT NULL
            )
        """)
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_epoch ON entries(epoch_ns)"
        )
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_topic ON entries(topic)"
        )
        self._db.commit()

    def write(self, ts: PRTTimestamp, topic: str, payload_bytes: bytes) -> None:
        with self._lock:
            offset = self._log_file.tell()
            self._log_file.write(payload_bytes)
            self._log_file.flush()
            self._db.execute(
                "INSERT INTO entries VALUES (?,?,?,?,?,?)",
                (ts.epoch_ns, ts.sequence, ts.source_id, topic, offset, len(payload_bytes)),
            )
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._log_file.close()
            self._db.close()


class TimelinePlayer:
    """Reads back a recorded session. Supports:
      - seek(epoch_ns): jump to nearest entry at/after a given time
      - play(speed=1.0): replay messages onto a callback at (scaled) real time
      - step(topic=None): advance one message, optionally filtered by topic
      - scrub(epoch_ns): like seek, but intended for UI drag-scrubbing
        (does not re-emit intermediate messages, just the nearest state)
    """

    def __init__(self, session_dir: Path):
        self.session_dir = session_dir
        self._index_path = session_dir / "session.prt_index"
        self._log_path = session_dir / "session.prtlog"
        self._db = sqlite3.connect(self._index_path, check_same_thread=False)
        self._log_file = open(self._log_path, "rb")
        self._cursor_epoch_ns = 0
        self._playing = False
        self._play_thread: Optional[threading.Thread] = None

    def duration_ns(self) -> int:
        row = self._db.execute("SELECT MAX(epoch_ns) FROM entries").fetchone()
        return row[0] or 0

    def entries_between(self, start_ns: int, end_ns: int, topic: Optional[str] = None) -> Iterator[TimelineEntry]:
        query = "SELECT epoch_ns, sequence, source_id, topic, byte_offset, byte_length FROM entries WHERE epoch_ns BETWEEN ? AND ?"
        params: list = [start_ns, end_ns]
        if topic:
            query += " AND topic = ?"
            params.append(topic)
        query += " ORDER BY epoch_ns ASC"
        for row in self._db.execute(query, params):
            yield TimelineEntry(*row)

    def read_payload(self, entry: TimelineEntry) -> bytes:
        self._log_file.seek(entry.byte_offset)
        return self._log_file.read(entry.byte_length)

    def seek(self, epoch_ns: int) -> Optional[TimelineEntry]:
        row = self._db.execute(
            "SELECT epoch_ns, sequence, source_id, topic, byte_offset, byte_length "
            "FROM entries WHERE epoch_ns >= ? ORDER BY epoch_ns ASC LIMIT 1",
            (epoch_ns,),
        ).fetchone()
        self._cursor_epoch_ns = epoch_ns
        return TimelineEntry(*row) if row else None

    def play(
        self,
        on_message: Callable[[TimelineEntry, bytes], None],
        speed: float = 1.0,
        start_ns: Optional[int] = None,
        end_ns: Optional[int] = None,
        blocking: bool = False,
    ) -> None:
        """Replay entries in a background thread, sleeping between messages
        scaled by `speed` so downstream consumers see realistic timing
        (speed=2.0 plays twice as fast, speed=0 = as-fast-as-possible)."""
        import time as _time

        start_ns = start_ns if start_ns is not None else self._cursor_epoch_ns
        end_ns = end_ns if end_ns is not None else self.duration_ns()

        def _run():
            self._playing = True
            last_epoch_ns = start_ns
            wall_start = _time.time()
            for entry in self.entries_between(start_ns, end_ns):
                if not self._playing:
                    break
                if speed > 0:
                    target_delta_s = (entry.epoch_ns - start_ns) / 1e9 / speed
                    actual_delta_s = _time.time() - wall_start
                    sleep_s = target_delta_s - actual_delta_s
                    if sleep_s > 0:
                        _time.sleep(sleep_s)
                payload = self.read_payload(entry)
                on_message(entry, payload)
                last_epoch_ns = entry.epoch_ns
            self._cursor_epoch_ns = last_epoch_ns
            self._playing = False

        if blocking:
            _run()
        else:
            self._play_thread = threading.Thread(target=_run, daemon=True)
            self._play_thread.start()

    def stop(self) -> None:
        self._playing = False
        if self._play_thread:
            self._play_thread.join(timeout=1.0)

    def close(self) -> None:
        self._log_file.close()
        self._db.close()
