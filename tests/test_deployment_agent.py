from pathlib import Path
import sys
import tempfile
import socket
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from core.runtime.agent import create_app
from core.runtime.project import ProjectDocument
from core.runtime.session import Runtime


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        sockets = [socket.socket(), socket.socket()]
        for sock in sockets: sock.bind(('127.0.0.1', 0))
        endpoints = ['tcp://127.0.0.1:' + str(sock.getsockname()[1]) for sock in sockets]
        for sock in sockets: sock.close()
        runtime = Runtime(pub_endpoint=endpoints[0], sub_endpoint=endpoints[1])
        self.client = TestClient(create_app('test-token-' * 4, self.directory.name, runtime))
        self.client.__enter__()
        self.headers = {'Authorization': 'Bearer ' + 'test-token-' * 4}
        self.document = ProjectDocument(name='Remote test', robot_urdf='<robot name="test"><link name="base_link"/></robot>', nodes=[{
            'node_id': 'imu', 'plugin_id': 'pyrobot.examples.fake_imu', 'plugin_version': '0.1.0', 'params': {}, 'urdf_link': 'base_link'}]).model_dump()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.directory.cleanup()

    def post(self, path, body):
        return self.client.post('/agent/' + path, json=body, headers=self.headers)

    def status(self):
        return self.client.get('/agent/status', headers=self.headers).json()

    def test_authentication_and_cors(self):
        for route in ('status', 'logs'):
            self.assertEqual(self.client.get('/agent/' + route).status_code, 401)
        for route in ('check', 'deploy', 'start', 'stop'):
            self.assertEqual(self.client.post('/agent/' + route, json={}).status_code, 401)
        response = self.client.get('/agent/status', headers={'Origin': 'http://localhost:5173'})
        self.assertEqual(response.headers['access-control-allow-origin'], 'http://localhost:5173')
        self.assertEqual(self.status()['protocol'], 1)

    def test_check_transfer_start_stop_and_stale_revision(self):
        result = self.post('check', self.document)
        self.assertTrue(result.json()['compatible'], result.text)
        self.assertIsNone(self.status()['revision'])
        response = self.post('deploy', self.document)
        self.assertEqual(response.status_code, 200, response.text)
        revision = response.json()['revision']
        self.assertTrue((Path(self.directory.name) / (revision + '.pyrobot.json')).is_file())
        self.assertFalse(self.status()['graph']['running'])
        self.assertEqual(self.post('start', {'revision': 'wrong'}).status_code, 409)
        response = self.post('start', {'revision': revision})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(self.status()['graph']['running'])
        self.assertEqual(self.post('deploy', self.document).status_code, 409)
        self.assertEqual(self.post('stop', {}).status_code, 200)
        self.assertFalse(self.status()['graph']['running'])
        logs = self.client.get('/agent/logs', headers=self.headers).json()['lines']
        self.assertTrue(any('Remote graph stopped' in line for line in logs))
        self.assertFalse(any('test-token-' in line for line in logs))

    def test_incompatible_or_invalid_upload_preserves_deployment(self):
        self.assertEqual(self.post('deploy', self.document).status_code, 200)
        before = self.status()['revision']
        self.document['nodes'][0]['plugin_version'] = 'missing-version'
        response = self.post('check', self.document)
        self.assertFalse(response.json()['compatible'])
        self.assertEqual(self.post('deploy', self.document).status_code, 422)
        self.assertEqual(self.status()['revision'], before)
        self.assertEqual(self.post('deploy', {'bad': 1}).status_code, 422)
        response = self.client.post('/agent/deploy', content=b'x' * (8 * 1024 * 1024 + 1), headers=self.headers)
        self.assertEqual(response.status_code, 413)
        self.assertEqual(self.status()['revision'], before)


if __name__ == '__main__': unittest.main()
