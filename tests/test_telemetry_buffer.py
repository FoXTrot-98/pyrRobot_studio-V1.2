# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.telemetry import TelemetryBuffer


class TelemetryBufferTests(unittest.TestCase):
    def test_paused_consumer_retains_only_recent_debug_packets(self):
        buffer = TelemetryBuffer()
        def publish():
            for i in range(10000):
                buffer.append({'topic': 'scan', 'seq': i})
        producer = threading.Thread(target=publish)
        producer.start()
        producer.join(timeout=2)
        self.assertFalse(producer.is_alive(), 'Telemetry must not wait for the browser')
        self.assertEqual([p['seq'] for p in buffer.drain()], list(range(10000-128, 10000)))
        self.assertEqual(buffer.drain(), [])

    def test_preview_keeps_latest_per_topic_and_bounds_topic_count(self):
        buffer = TelemetryBuffer(preview=True)
        for seq in range(1000):
            for topic in ('scan', 'map', 'command'):
                buffer.append({'topic': topic, 'seq': seq})
        self.assertEqual(buffer.drain(), [{'topic': topic, 'seq': 999} for topic in ('scan', 'map', 'command')])
        for seq in range(300):
            buffer.append({'topic': str(seq)})
        self.assertEqual(buffer.drain(), [{'topic': str(i)} for i in range(44, 300)])

    def test_disconnect_discards_pending_and_late_callbacks(self):
        for preview in (False, True):
            buffer = TelemetryBuffer(preview=preview)
            buffer.append({'topic': 'map'})
            buffer.close()
            buffer.append({'topic': 'late'})
            self.assertEqual(buffer.drain(), [])


if __name__ == '__main__':
    unittest.main()
