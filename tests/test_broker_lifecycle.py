# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

import socket
import sys
import time
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.bus.base import Bus, ZmqTransport
from core.bus.broker import run_broker
from core.timing.clock import PRTClock


class BrokerLifecycleTests(unittest.TestCase):
    def endpoints(self):
        sockets = [socket.socket(), socket.socket()]
        try:
            for sock in sockets:
                sock.bind(('127.0.0.1', 0))
            return [f'tcp://127.0.0.1:{sock.getsockname()[1]}' for sock in sockets]
        finally:
            for sock in sockets:
                sock.close()

    def test_burst_forwarding_shutdown_and_endpoint_reuse(self):
        endpoints = self.endpoints()
        for _ in range(2):
            stop, ready, received = threading.Event(), threading.Event(), threading.Event()
            errors, packets = [], []
            thread = threading.Thread(target=run_broker, args=(*endpoints, stop, ready, errors), daemon=True)
            thread.start()
            bus = None
            try:
                self.assertTrue(ready.wait(3))
                self.assertEqual(errors, [])
                clock = PRTClock(source_id='test')
                clock.set_epoch_origin(time.time_ns())
                bus = Bus(ZmqTransport(*endpoints), clock)
                def collect(msg):
                    packets.append(msg.payload['seq'])
                    if msg.payload['seq'] == 299:
                        received.set()
                bus.subscribe('burst/', collect)
                bus.wait_ready(['burst/sensor', 'burst/control'])
                for seq in range(300):
                    bus.publish('burst/control' if seq % 10 == 9 else 'burst/sensor', {'seq': seq})
                self.assertTrue(received.wait(3), 'Broker failed to drain mixed traffic')
                self.assertEqual(packets, list(range(300)))
            finally:
                if bus is not None:
                    bus.close()
                stop.set()
                thread.join(timeout=3)
            self.assertFalse(thread.is_alive(), 'Native proxy did not terminate')
            self.assertEqual(errors, [])

    def test_stop_requested_before_proxy_start(self):
        stop, ready = threading.Event(), threading.Event()
        stop.set()
        errors = []
        thread = threading.Thread(target=run_broker, args=(*self.endpoints(), stop, ready, errors), daemon=True)
        thread.start()
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        self.assertTrue(ready.is_set())
        self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
