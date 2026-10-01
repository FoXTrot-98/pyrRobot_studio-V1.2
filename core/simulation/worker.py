# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Latest-message mailboxes keep heavy mapping/rendering off the bus thread."""
import threading
from sdk.pyrobot_plugin import Node


class WorkerNode(Node):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._mail_lock = threading.Condition()
        self._mail = {}
        self._stop = threading.Event()

    def start_worker(self):
        with self._mail_lock:
            self._mail.clear()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._work, name=self.node_id, daemon=True)
        self._thread.start()

    def on_message(self, port, message):
        with self._mail_lock:
            self._mail[port] = message
            self._mail_lock.notify()

    def _work(self):
        try:
            while not self._stop.is_set():
                with self._mail_lock:
                    self._mail_lock.wait_for(lambda: self._mail or self._stop.is_set(), timeout=.2)
                    messages, self._mail = self._mail, {}
                for port, message in messages.items():
                    if self._stop.is_set():
                        break
                    with self.processing(message):
                        self.process(port, message.payload)
                if not self._stop.is_set():
                    self.on_tick()
        except Exception as exc:
            self.fail(exc)
            self.log.exception("Simulation worker failed")
            self._stop.set()

    def on_stop(self):
        self._stop.set()
        with self._mail_lock:
            self._mail_lock.notify_all()

    def on_tick(self):
        """Called after processing or at most every 0.2 seconds while idle."""

    def on_params_changed(self, updated):
        # These nodes read tunable values for each incoming observation.
        pass
