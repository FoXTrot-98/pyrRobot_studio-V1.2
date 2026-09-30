"""Saved-map validation, project/API round trips, and explicit startup pose."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.simulation.saved_map import SavedMap
from core.simulation.navigation import LidarSlam
from core.simulation.world import FourWheelSimulator
from core.simulation.config import RobotConfiguration
from core.runtime.project import ProjectDocument,prepare_project
from plugins.user.lidar_slam import LidarSlamNode

ROOT=Path(__file__).resolve().parents[1]

class MapTests(unittest.TestCase):
    def snapshot(self):
        config=RobotConfiguration()
        grid=np.zeros((config.mapping.height,config.mapping.width),dtype=int)
        grid[0,:]=100
        grid[-1,:]=-1
        return SavedMap(name='Room',grid=grid.tolist(),origin=config.mapping.origin,resolution=config.mapping.resolution,
            captured_pose=[1,0,0],home_poses={'nav':[0,0,0]},environment=config.environment.model_dump(mode='json'))

    def test_validation_rejects_malformed_and_incompatible_maps(self):
        saved=self.snapshot()
        for grid in ([],[[]],[[0,0],[0]],[[3]],[[True]],[[0]*513]):
            with self.subTest(grid=str(grid)[:30]),self.assertRaises(ValueError):
                SavedMap.model_validate({**saved.model_dump(),'grid':grid})
        config=RobotConfiguration()
        config.mapping.resolution=.2
        with self.assertRaises(ValueError):saved.check_config(config)
        with self.assertRaises(ValueError):ProjectDocument(saved_maps={'slam':saved})

    def test_restore_requires_pose_and_resets_confirmation(self):
        node=LidarSlamNode(node_id='slam',bus=Mock())
        node.saved_map=self.snapshot()
        with self.assertRaisesRegex(ValueError,'starting pose'):node.on_start()
        node.map_start_pose=[1.,0.,.5]
        with patch.object(node,'start_worker'):node.on_start()
        self.assertEqual(node.slam.pose.tolist(),[1.,0.,.5])
        self.assertEqual(node.slam.grid[0,0],4.)
        self.assertEqual(node.slam.grid[-1,0],0.)
        self.assertEqual(node.slam.grid[1,1],-4.)
        node.on_stop()
        self.assertIsNone(node.map_start_pose)

    def test_api_capture_export_import_and_initialize(self):
        from fastapi.testclient import TestClient
        from backend.app import main
        with patch.object(main,'init_rerun'),TestClient(main.app) as client:
            document=json.loads((ROOT/'examples/four-wheel/teleoperation.pyrobot.json').read_text())
            self.assertEqual(client.post('/api/project/import',json=document).status_code,200)
            self.assertEqual(client.post('/api/project/maps/nav',json={'name':'Empty'}).status_code,400)
            node=main.runtime.graph.nodes['slam'].node_obj
            sim=FourWheelSimulator();slam=LidarSlam()
            scan=sim.scan([.05,0,0]);slam.update([0,0,0],scan)
            node._latest_state=slam.state(scan,1.)
            main.runtime.graph.nodes['nav'].node_obj._home_pose=[0.,0.,0.]
            captured=client.post('/api/project/maps/nav',json={'name':'Lab'})
            self.assertEqual(captured.status_code,200,captured.text)
            self.assertEqual(captured.json()['snapshot']['home_poses']['nav'],[0,0,0])
            saved=client.post('/api/project/export',json={'name':'Mapped robot','positions':{}}).json()
            self.assertEqual(saved['schema_version'],4)
            self.assertEqual(saved['saved_maps']['slam']['name'],'Lab')
            next(n for n in saved['nodes'] if n['node_id']=='nav')['params']['home_pose']=[]
            self.assertEqual(client.post('/api/project/import',json=saved).status_code,200)
            self.assertEqual(main.runtime.graph.nodes['nav'].node_obj.get_param('home_pose'),[0.,0.,0.])
            node=main.runtime.graph.nodes['slam'].node_obj
            self.assertIsNone(node.map_start_pose)
            started=client.post('/api/graph/start')
            self.assertEqual(started.status_code,400,started.text)
            self.assertIn('starting pose',started.text)
            self.assertFalse(main.runtime.graph.to_dict()['running'])
            self.assertEqual(client.post('/api/project/maps/nav/initialize',json={'pose':[999,0,0]}).status_code,400)
            initialized=client.post('/api/project/maps/nav/initialize',json={'pose':[0,0,0]})
            self.assertEqual(initialized.status_code,200,initialized.text)
            with patch.object(node,'start_worker'):node.on_start()
            self.assertGreater(np.count_nonzero(node.slam.grid),0)
            node.on_stop()
            changed=main.runtime.graph.robot_config.model_dump(mode='json')
            changed['mapping']['width']+=1
            self.assertEqual(client.patch('/api/project/robot-config',json=changed).status_code,400)
            client.patch('/api/graph/nodes/nav/params',json={'params':{'home_pose':[.3,.2,0.]}})
            edited=client.post('/api/project/export',json={'name':'Edited home','positions':{}}).json()
            self.assertEqual(next(n for n in edited['nodes'] if n['node_id']=='nav')['params']['home_pose'],[.3,.2,0.])
            self.assertEqual(client.delete('/api/project/maps/nav').status_code,200)
            self.assertIsNone(node.saved_map)
            fresh=client.post('/api/project/export',json={'name':'Fresh','positions':{}}).json()
            self.assertEqual(fresh['schema_version'],2)
            self.assertEqual(next(n for n in fresh['nodes'] if n['node_id']=='nav')['params']['home_pose'],[])
            node.saved_map=SavedMap.model_validate(captured.json()['snapshot'])
            self.assertEqual(client.delete('/api/graph/nodes/nav').status_code,200)
            remaining=client.post('/api/project/export',json={'name':'Map only','positions':{}})
            self.assertEqual(remaining.status_code,200,remaining.text)
            self.assertEqual(remaining.json()['saved_maps']['slam']['home_poses'],{})

if __name__=='__main__':unittest.main()
