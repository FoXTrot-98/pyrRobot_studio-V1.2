# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from backend.app import main
from core.messages import JointTargets
from core.simulation.webots_examples import PROFILES, attach_controller, example_project


class NativeExamplesTests(unittest.TestCase):
    def test_world_preserves_nested_fields_and_original_environment(self):
        source = '''#VRML_SIM R2025a utf8
WorldInfo { basicTimeStep 16 }
DEF ROBOT Panda {
  controller "old"
  controllerArgs [ "demo" ]
  supervisor FALSE
  window "old"
  name "quoted } bracket ["
  children [ Robot { controller "nested" } ]
}
Floor { size 10 10 }
'''
        result = attach_controller(source, 'Panda', 'studio_bridge', ['12', 'token'])
        self.assertIn('controller "nested"', result)
        self.assertIn('name "quoted } bracket ["', result)
        self.assertIn('Floor { size 10 10 }', result)
        self.assertIn('supervisor TRUE', result)
        self.assertNotIn('"old"', result)
        self.assertNotIn('"demo"', result)
        for invalid in ('Floor {}', 'Panda {} Panda {}'):
            with self.assertRaises(ValueError): attach_controller(invalid, 'Panda', 'bridge', [])

    def test_joint_targets_reject_nonfinite_and_empty(self):
        for positions in ({}, {'joint': float('nan')}, {'joint': float('inf')}):
            with self.assertRaises(ValueError): JointTargets(positions=positions)

    def test_catalog_and_projects_import_without_urdf(self):
        with patch.object(main, 'init_rerun'), TestClient(main.app) as client:
            catalog = client.get('/api/examples/webots')
            self.assertEqual(catalog.status_code, 200)
            self.assertEqual({e['id'] for e in catalog.json()}, set(PROFILES))
            self.assertEqual(client.get('/api/examples/webots/missing').status_code, 404)
            for profile in PROFILES:
                document = client.get('/api/examples/webots/' + profile).json()
                self.assertEqual(document, example_project(profile))
                checked_in = Path(__file__).resolve().parents[1] / 'examples/webots' / (profile + '.pyrobot.json')
                self.assertEqual(json.loads(checked_in.read_text()), document)
                response = client.post('/api/project/import', json=document)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIsNone(response.json()['robot'])
                graph = client.get('/api/graph').json()
                self.assertFalse(graph['running'])
                self.assertEqual(len(graph['nodes']), 3 if profile == 'youbot' else 2)


if __name__ == '__main__': unittest.main()
