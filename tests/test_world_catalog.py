"""External world selection and source isolation regression checks."""
import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from backend.app import main
from core.simulation.external_world import inspect, compose, wheel_contacts, blocks
from core.simulation.webots_project import find_webots
ROOT=Path(__file__).resolve().parents[1]
WORLD=ROOT/'tests/fixtures/external-room.wbt'

class WheelContactTests(unittest.TestCase):
    def test_tuning_shared_profile_updates_both_world_generators(self):
        from core.simulation.webots_project import generate_project
        from core.simulation.config import RobotConfiguration
        from core.urdf.model import load_urdf
        model = load_urdf(ROOT/'examples/four-wheel/robot.urdf')
        with patch('core.simulation.wheel_contact.WHEEL_FRICTION', .63), patch(
                'core.simulation.wheel_contact.WHEEL_FORCE_DEPENDENT_SLIP', .017), tempfile.TemporaryDirectory() as folder:
            generated = generate_project(folder, model, RobotConfiguration(), 12345, 'test-token').read_text()
            imported = wheel_contacts('WorldInfo {} Solid { contactMaterial "ice" }')
        for world in (generated, imported):
            self.assertIn('coulombFriction [ 0.63 ] forceDependentSlip [ 0.017 ]', world)
            self.assertNotIn('coulombFriction [ 0.8 ]', world)

    def test_import_retains_environment_contacts_and_adds_private_wheel_pairs(self):
        original='ContactProperties { material1 "ice" material2 "default" coulombFriction [ 0.1 ] }'
        source='WorldInfo { contactProperties [ '+original+' ] } Solid { contactMaterial "ice" }'
        adapted=wheel_contacts(source)
        self.assertIn(original,adapted)
        self.assertEqual(adapted.count('contactProperties ['),1)
        self.assertIn('material1 "pyrobot_studio_wheel" material2 "ice"',adapted)
        self.assertIn('material1 "pyrobot_studio_wheel" material2 "default"',adapted)
        self.assertIn('forceDependentSlip [ 0.02 ]',adapted)
        self.assertEqual([b[0] for b in blocks(adapted) if b[3]],['WorldInfo','Solid'])
        with self.assertRaisesRegex(ValueError,'reserved contact material'):
            wheel_contacts('WorldInfo {} Solid { contactMaterial "pyrobot_studio_wheel" }')

@unittest.skipUnless(find_webots(),"Webots installation required for node/PROTO metadata")
class WorldTests(unittest.TestCase):
    def setUp(self):
        self.mock=patch.object(main,'init_rerun');self.mock.start()
        self.client=TestClient(main.app);self.client.__enter__()
    def tearDown(self):
        self.client.__exit__(None,None,None);self.mock.stop()
    def choice(self):
        c=self.client.get('/api/simulation/worlds').json()
        return dict(path=str(WORLD),revision=c['revision'],spawn_pose=[1,1,.5],bounds=[-10,-10,10,10],resolution=.15,reset_mission=True)
    def test_source_is_preserved_and_only_our_robot_is_inserted(self):
        before=WORLD.read_bytes(); info=inspect(WORLD)
        self.assertEqual(info['removed_robots'],['Robot'])
        text=compose(WORLD,'DEF PYROBOT Robot { controller "ours" }',expected_hash=info['sha256'])
        self.assertIn('DEF TEST_WALL Solid',text);self.assertNotIn('must_not_run',text)
        self.assertEqual(text.count('Robot {'),1);self.assertEqual(before,WORLD.read_bytes())
        with self.assertRaisesRegex(ValueError,'changed'):compose(WORLD,'Robot {}',expected_hash='stale')
    def test_rejects_unsupported_world_structures(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'unsupported.wbt'
            for source,message in [
                ('WorldInfo { coordinateSystem "NUE" }','ENU'),
                ('WorldInfo {} Solid { children [ Robot {} ] }','Nested robots'),
                ('WorldInfo { physics "custom" }','physics plugins'),
                ('WorldInfo {} DEF PYROBOT Solid {}','rename'),
            ]:
                path.write_text('#VRML_SIM R2025a utf8\n'+source)
                with self.assertRaisesRegex(ValueError,message):inspect(path)
    def test_world_first_then_robot_setup(self):
        choice=self.choice()
        before=self.client.get('/api/graph').json()
        response=self.client.post('/api/simulation/worlds/preview',json=choice)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(before,self.client.get('/api/graph').json())
        choice['source_hash']=response.json()['sha256']
        response=self.client.post('/api/simulation/worlds/apply',json=choice)
        self.assertEqual(response.status_code,200,response.text)
        initial=self.client.get('/api/robot/setup').json()
        self.assertEqual(initial['robot_config']['webots_world'],str(WORLD))
        self.assertEqual(initial['node_count'],0)
        draft=dict(robot_urdf=initial['reference_urdf'],robot_config=initial['robot_config'],target='webots',revision=initial['revision'],name='Imported world',positions={})
        response=self.client.post('/api/robot/setup/apply',json=draft)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.client.get('/api/graph/preflight').json()['diagnostics'],[])
        self.assertEqual(self.client.post('/api/simulation/worlds/apply',json=choice).status_code,400)
    def test_existing_graph_converts_without_losing_robot(self):
        initial=self.client.get('/api/robot/setup').json()
        draft=dict(robot_urdf=initial['reference_urdf'],robot_config=initial['robot_config'],target='builtin',revision=initial['revision'],name='Robot',positions={})
        response=self.client.post('/api/robot/setup/apply',json=draft)
        self.assertEqual(response.status_code,200,response.text)
        choice=self.choice();preview=self.client.post('/api/simulation/worlds/preview',json=choice)
        self.assertEqual(preview.status_code,200,preview.text)
        choice['source_hash']=preview.json()['sha256']
        response=self.client.post('/api/simulation/worlds/apply',json=choice)
        self.assertEqual(response.status_code,200,response.text)
        doc=self.client.post('/api/project/export',json={'name':'Robot','positions':{}}).json()
        self.assertEqual(doc['robot_urdf'],initial['reference_urdf'])
        self.assertFalse(doc['saved_maps'])
        self.assertTrue(any(n['plugin_id']=='pyrobot.sim.webots' for n in doc['nodes']))
        self.assertEqual(next(n for n in doc['nodes'] if n['node_id']=='drive')['params']['mode'],'stopped')

if __name__=='__main__':unittest.main()
