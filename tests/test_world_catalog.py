# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""External world selection and source isolation regression checks."""
import sys
import unittest
import tempfile
import io
import json
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from backend.app import main
from core.simulation.external_world import inspect, compose, wheel_contacts, blocks
from core.simulation.webots_project import find_webots
ROOT=Path(__file__).resolve().parents[1]
WORLD=ROOT/'tests/fixtures/external-room.wbt'

class StartupDiagnosticsTests(unittest.TestCase):
    def test_controller_failure_is_persisted_and_reported_to_studio(self):
        from plugins.user.webots_sim import WebotsSimulation
        node = WebotsSimulation(node_id='sim', bus=Mock())
        connection = Mock()
        connection.makefile.return_value = io.BytesIO(b'{"token":"test"}\n{"error":"Unsafe spawn: body intersects wall"}\n')
        node._server = Mock()
        node._server.accept.return_value = (connection, ('127.0.0.1', 1))
        with tempfile.TemporaryDirectory() as folder:
            node.directory = Path(folder)
            with self.assertLogs(node.log, level='ERROR'):
                node._run('test')
            result = json.loads((node.directory/'status.json').read_text())
            self.assertEqual(result['stage'], 'failed')
            self.assertIn('body intersects wall', result['error'])
            self.assertEqual(node.state, 'failed')
            self.assertIn('status.json', node.error)
            self.assertTrue(node._stop.is_set())

class WheelContactTests(unittest.TestCase):
    def test_tuning_shared_profile_updates_both_world_generators(self):
        from core.simulation.webots_project import generate_project
        from core.simulation.config import RobotConfiguration
        from core.urdf.model import load_urdf
        model = load_urdf(ROOT/'examples/four-wheel/robot.urdf')
        config = RobotConfiguration(physics={'wheel_friction':.63,'wheel_slip':.017,
            'body_mass':12,'wheel_mass':.5,'motor_max_velocity':7,'motor_max_torque':3,'wheel_damping':.04})
        with tempfile.TemporaryDirectory() as folder:
            generated = generate_project(folder, model, config, 12345, 'test-token').read_text()
            imported = wheel_contacts('WorldInfo {} Solid { contactMaterial "ice" }', physics=config.physics)
            if find_webots():
                config.webots_world=str(WORLD)
                composed=generate_project(folder,model,config,12345,'test-token').read_text()
                self.assertIn('coulombFriction [ 0.63 ] forceDependentSlip [ 0.017 ]',composed)
                self.assertIn('maxVelocity 7 maxTorque 3',composed)
        self.assertIn('density -1 mass 12 centerOfMass',generated)
        self.assertEqual(generated.count('density -1 mass 0.5'),4)
        self.assertEqual(generated.count('maxVelocity 7 maxTorque 3'),4)
        self.assertEqual(generated.count('dampingConstant 0.04'),4)
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

    def test_asset_fields_do_not_rewrite_names_and_dependencies_change_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            mesh=root/'floor.obj';mesh.write_text('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n')
            proto=root/'FloorPart.proto'
            proto.write_text('#VRML_SIM R2025a utf8\nPROTO FloorPart [] { Solid { children [ Shape { geometry Mesh { url [ "floor.obj" ] } } ] } }')
            world=root/'world.wbt'
            world.write_text('#VRML_SIM R2025a utf8\nEXTERNPROTO "FloorPart.proto"\nWorldInfo {}\nFloorPart {}\nSolid { name "wall.png" }')
            first=inspect(world)
            self.assertIn('name "wall.png"',first['source'])
            self.assertIn(str(mesh.resolve()),first['local_asset_hashes'])
            mesh.write_text(mesh.read_text().replace('v 1 0 0','v 4 0 0'))
            second=inspect(world)
            self.assertNotEqual(first['sha256'],second['sha256'])
            with self.assertRaisesRegex(ValueError,'changed'):
                compose(world,'Robot {}',expected_hash=first['sha256'])
            proto.write_text(proto.read_text().replace('Solid {','Solid { translation 1 0 0'))
            self.assertNotEqual(second['sha256'],inspect(world)['sha256'])
            world.write_text('#VRML_SIM R2025a utf8\nWorldInfo {}\nShape { geometry Mesh { url [ "missing.obj" ] } }')
            with self.assertRaisesRegex(ValueError,'Missing local world asset'):
                inspect(world)
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
        self.assertEqual(response.status_code,400,response.text)
        self.assertIn('placement',response.text)
        with patch.object(main, 'placement_preview') as physical_check:
            response=self.client.post('/api/simulation/worlds/apply',json=choice)
            self.assertEqual(response.status_code,200,response.text)
            physical_check.require_valid.assert_called_once()
        doc=self.client.post('/api/project/export',json={'name':'Robot','positions':{}}).json()
        self.assertEqual(doc['robot_urdf'],initial['reference_urdf'])
        self.assertFalse(doc['saved_maps'])
        self.assertTrue(any(n['plugin_id']=='pyrobot.sim.webots' for n in doc['nodes']))
        self.assertEqual(next(n for n in doc['nodes'] if n['node_id']=='drive')['params']['mode'],'stopped')

    def test_old_clearance_can_be_repaired_before_rechecking_stale_world(self):
        from core.runtime.project import ProjectDocument
        document=ProjectDocument.model_validate_json((ROOT/'examples/four-wheel/webots.pyrobot.json').read_text())
        document.robot_config.webots_world=str(WORLD)
        document.robot_config.webots_world_hash='old-source-only-hash'
        document.robot_config.drive.collision_radius=.48
        main.runtime.load_project(document)
        initial=self.client.get('/api/robot/setup').json()
        initial['robot_config']['drive']['collision_radius']=.55
        request=dict(robot_urdf=initial['robot_urdf'],robot_config=initial['robot_config'],
                     name='Repaired clearance',target='configure',revision=initial['revision'],positions={})
        response=self.client.post('/api/robot/setup/preview',json=request)
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(any('Source world' in warning for warning in response.json()['warnings']))
        response=self.client.post('/api/robot/setup/apply',json=request)
        self.assertEqual(response.status_code,200,response.text)
        self.assertFalse(self.client.get('/api/graph/preflight').json()['ready'])
        response=self.client.post('/api/simulation/worlds/preview',json=self.choice())
        self.assertEqual(response.status_code,200,response.text)

if __name__=='__main__':unittest.main()
