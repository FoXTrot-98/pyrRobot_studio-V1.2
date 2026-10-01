# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

import base64
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from backend.app.security import StudioSecurity
from plugins.devices.can_writer import CanBusWriterNode
from core.bus.base import Bus
from core.timing.clock import PRTClock
from test_runtime_projects import MemoryTransport
from core.runtime.graph import NodeGraph
from core.runtime.plugin_registry import PluginRegistry


class IndustrialHardeningTests(unittest.TestCase):
    def test_http_websocket_origin_and_authentication(self):
        app = FastAPI()
        app.add_middleware(StudioSecurity)
        @app.get('/')
        def index(): return {'ok': True}
        @app.websocket('/ws')
        async def ws(socket: WebSocket):
            await socket.accept()
            await socket.send_text('ok')
        with patch.dict(os.environ, {'PYROBOT_STUDIO_TOKEN': 'x' * 32}), TestClient(app) as client:
            self.assertEqual(client.get('/').status_code, 401)
            self.assertEqual(client.get('/', headers={'Authorization': 'Bearer ' + 'x' * 32}).status_code, 200)
            self.assertEqual(client.get('/', headers={'Authorization': 'Bearer ' + 'x' * 32, 'Origin': 'https://evil.example'}).status_code, 403)
            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect('/ws'): pass
            encoded = base64.urlsafe_b64encode(b'x' * 32).decode().rstrip('=')
            with client.websocket_connect('/ws', subprotocols=['pyrobot', 'auth.' + encoded]) as socket:
                self.assertEqual(socket.receive_text(), 'ok')
        with patch.dict(os.environ, {'PYROBOT_STUDIO_TOKEN': ''}), TestClient(app, client=('192.0.2.1', 5000)) as client:
            self.assertEqual(client.get('/').status_code, 403)

    def test_can_io_runs_off_callback_and_expires_queued_commands(self):
        entered, release = threading.Event(), threading.Event()
        device = MagicMock()
        calls = []
        def send(frame, timeout):
            calls.append((frame.arbitration_id, timeout, threading.current_thread().name))
            entered.set()
            release.wait(1)
        device.send.side_effect = send
        node = CanBusWriterNode(node_id='can-test', bus=Bus(MemoryTransport(), PRTClock('test')),
            params={'send_timeout': .1, 'max_queue_age': .01})
        with patch('can.interface.Bus', return_value=device):
            node.start()
            try:
                node.on_message('frame', SimpleNamespace(payload={'arbitration_id': 1, 'data_hex': '00'}))
                self.assertTrue(entered.wait(1))
                node.on_message('frame', SimpleNamespace(payload={'arbitration_id': 2, 'data_hex': '00'}))
                time.sleep(.03)
                release.set()
                deadline = time.monotonic() + 1
                while node.state != 'failed' and time.monotonic() < deadline: time.sleep(.01)
                self.assertEqual(node.state, 'failed')
                self.assertIn('expired', node.error)
                self.assertEqual(calls, [(1, .1, 'can-test')])
            finally:
                release.set()
                node.stop()
        device.shutdown.assert_called_once()

    def test_stalled_transport_stops_graph(self):
        transport = MemoryTransport()
        transport.last_progress = time.monotonic() - 3
        graph = NodeGraph(Bus(transport, PRTClock('test')), PluginRegistry())
        graph.start()
        deadline = time.monotonic() + 1
        while graph.to_dict()['running'] and time.monotonic() < deadline: time.sleep(.01)
        self.assertFalse(graph.to_dict()['running'])
        self.assertIn('transport', graph.failure_reason)
        graph.close()


if __name__ == '__main__': unittest.main()
