# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from backend.app import main
from core.runtime.robot_setup import inspect_robot, EXAMPLE


class RobotSetupTests(unittest.TestCase):
    def setUp(self):
        self.rerun = patch.object(main,'init_rerun'); self.rerun.start()
        self.client = TestClient(main.app); self.client.__enter__()
        initial = self.client.get('/api/robot/setup').json()
        self.draft = dict(robot_urdf=initial['reference_urdf'], robot_config=inspect_robot(initial['reference_urdf'])['suggested_config'],
                          name='My guided robot',target='builtin',revision=initial['revision'],positions={})

    def tearDown(self):
        self.client.__exit__(None,None,None); self.rerun.stop()

    def test_inspection_and_preview_are_read_only_then_apply_creates_stopped_graph(self):
        before = self.client.get('/api/graph').json()
        response = self.client.post('/api/robot/setup/inspect',json={'robot_urdf':self.draft['robot_urdf']})
        self.assertEqual(response.status_code,200,response.text)
        model = response.json()
        self.assertEqual(model['suggested_config']['drive']['left_joints'],['front_left_wheel_joint','rear_left_wheel_joint'])
        self.assertTrue(any(link['faces'] for link in model['links']))
        checked = self.client.post('/api/robot/setup/preview',json=self.draft)
        self.assertEqual(checked.status_code,200,checked.text)
        self.assertAlmostEqual(checked.json()['track'],.62)
        self.assertEqual(self.client.get('/api/graph').json(),before)
        self.assertIsNone(self.client.get('/api/project').json()['robot'])
        applied = self.client.post('/api/robot/setup/apply',json=self.draft)
        self.assertEqual(applied.status_code,200,applied.text)
        graph = self.client.get('/api/graph').json()
        self.assertFalse(graph['running']); self.assertEqual(len(graph['nodes']),7)
        drive = next(n for n in graph['nodes'] if n['node_id']=='drive')
        self.assertEqual(drive['params']['mode'],'stopped')
        self.assertEqual(self.client.get('/api/graph/preflight').json()['diagnostics'],[])
        exported = self.client.post('/api/project/export',json={'name':'Saved setup','positions':applied.json()['positions']}).json()
        self.assertEqual(exported['robot_config'],self.draft['robot_config'])
        self.assertEqual(exported['robot_urdf'],self.draft['robot_urdf'])

    def test_invalid_assignments_and_models_do_not_replace_project(self):
        before = self.client.get('/api/graph').json()
        bad = copy.deepcopy(self.draft)
        bad['robot_config']['drive']['lidar_frame']='missing_lidar'
        response = self.client.post('/api/robot/setup/apply',json=bad)
        self.assertEqual(response.status_code,400,response.text)
        self.assertEqual(self.client.get('/api/graph').json(),before)
        bad = copy.deepcopy(self.draft)
        bad['robot_config']['drive']['right_joints']=bad['robot_config']['drive']['left_joints']
        self.assertEqual(self.client.post('/api/robot/setup/preview',json=bad).status_code,422)
        for xml in ('<robot name="bad"><link name="a"/><link name="a"/></robot>',
                    '<robot name="bad"><link name="a"/><link name="b"/></robot>',
                    '<robot name="bad"><link name="a"/><joint name="j" type="fixed"><parent link="a"/><child link="missing"/></joint></robot>'):
            self.assertEqual(self.client.post('/api/robot/setup/inspect',json={'robot_urdf':xml}).status_code,400)

    def test_configure_preserves_graph_and_rebinds_simulator_base(self):
        self.assertEqual(self.client.post('/api/robot/setup/apply',json=self.draft).status_code,200)
        self.client.patch('/api/graph/nodes/nav/params',json={'params':{'max_speed':.3}})
        initial = self.client.get('/api/robot/setup').json()
        self.draft.update(revision=initial['revision'],target='configure',positions={'sim':{'x':123,'y':456}})
        self.draft['robot_urdf']=self.draft['robot_urdf'].replace('base_link','chassis')
        self.draft['robot_config']['drive']['base_frame']='chassis'
        response = self.client.post('/api/robot/setup/apply',json=self.draft)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['positions']['sim'],{'x':123,'y':456})
        nodes = self.client.get('/api/graph').json()['nodes']
        self.assertEqual(next(n for n in nodes if n['node_id']=='sim')['urdf_link'],'chassis')
        self.assertEqual(next(n for n in nodes if n['node_id']=='nav')['params']['max_speed'],.3)

    def test_stale_draft_and_running_graph_are_rejected(self):
        self.client.post('/api/graph/nodes',json={'node_id':'logger','plugin_id':'pyrobot.examples.logger'})
        response = self.client.post('/api/robot/setup/apply',json=self.draft)
        self.assertEqual(response.status_code,400)
        self.assertIn('project changed',response.json()['detail'])
        self.assertEqual(len(self.client.get('/api/graph').json()['nodes']),1)
        self.client.delete('/api/graph/nodes/logger')
        self.draft['revision']=self.client.get('/api/robot/setup').json()['revision']
        self.assertEqual(self.client.post('/api/graph/start').status_code,200)
        response = self.client.post('/api/robot/setup/apply',json=self.draft)
        self.assertEqual(response.status_code,400)
        self.assertIn('Stop the graph',response.json()['detail'])


if __name__=='__main__': unittest.main()
