# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Bound browser telemetry on the producer thread, before any asyncio handoff."""
from collections import deque
import threading


class TelemetryBuffer:
    def __init__(self, *, preview=False):
        self.preview = preview
        self._pending = {}
        self._queue = deque(maxlen=128)
        self._lock = threading.Lock()
        self._closed = False

    def append(self, payload):
        with self._lock:
            if self._closed:
                return
            if self.preview:
                self._pending[payload['topic']] = payload
                if len(self._pending) > 256:
                    del self._pending[next(iter(self._pending))]
            else:
                self._queue.append(payload)

    def drain(self):
        with self._lock:
            batch = list(self._pending.values()) if self.preview else list(self._queue)
            self._pending.clear()
            self._queue.clear()
            return batch

    def close(self):
        with self._lock:
            self._closed = True
            self._pending.clear()
            self._queue.clear()
