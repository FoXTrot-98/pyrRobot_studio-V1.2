"""Builder meshes survive setup, project persistence, rendering and simulation."""
import copy
import io
import json
import logging
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from backend.app import main
from core.urdf.builder import Model, bundle
from core.urdf.assets import builder_package, read_builder_bundle, MeshAsset, attach_assets
from core.urdf.model import parse_urdf
from core.runtime.robot_setup import inspect_robot
from core.runtime.project import ProjectDocument
from core.simulation.config import RobotConfiguration
from core.simulation.webots_project import generate_project
from core.simulation.mesh_robot import collision_body

ROOT=Path(__file__).resolve().parents[1]
def custom_model():
    return Model.model_validate_json((ROOT/'examples/model-builder/four-wheel-rover.robot-builder.json').read_text())


class MeshWorkflowTests(unittest.TestCase):
    def test_bundle_matches_handoff_and_preserves_geometry_normals_colors(self):
        model=custom_model()
        package=builder_package(model)
        self.assertEqual(read_builder_bundle(bundle(model)[0]),package)
        assets={k:MeshAsset.model_validate(v) for k,v in package['robot_assets'].items()}
        inspected=inspect_robot(package['robot_urdf'],assets)
        self.assertFalse(inspected['warnings'])
        for link in inspected['links']:
            if not link['vertices']: continue
            original=next(p for p in model.parts if p.id==link['name'])
            np.testing.assert_allclose(np.min(link['vertices'],axis=0),np.min(original.vertices,axis=0),atol=1e-10)
            np.testing.assert_allclose(np.max(link['vertices'],axis=0),np.max(original.vertices,axis=0),atol=1e-10)
            self.assertTrue(link['colors'])
            np.testing.assert_allclose(np.linalg.norm(link['normals'],axis=1),1)

    def test_unsafe_or_incomplete_assets_are_rejected(self):
        package=builder_package(custom_model())
        robot=parse_urdf(package['robot_urdf'])
        assets={k:MeshAsset.model_validate(v) for k,v in package['robot_assets'].items()}
        first=next(iter(assets))
        with self.assertRaises(ValueError): attach_assets(robot,{first:assets[first]})
        with self.assertRaises(ValueError): attach_assets(robot,{'../outside.stl':assets[first]})
        corrupt=assets[first].model_dump();corrupt['faces'][0][0]=999999
        with self.assertRaises(ValueError): MeshAsset.model_validate(corrupt)
        with self.assertRaises(ValueError): read_builder_bundle(b'not a zip')
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as archive: archive.writestr('../robot-builder.json','{}')
        with self.assertRaises(ValueError): read_builder_bundle(stream.getvalue())

    def test_mesh_webots_world_is_self_contained_and_uses_custom_visuals(self):
        package=builder_package(custom_model())
        robot=attach_assets(parse_urdf(package['robot_urdf']),{k:MeshAsset.model_validate(v) for k,v in package['robot_assets'].items()})
        config=RobotConfiguration()
        config.drive.wheel_radius=.12
        with tempfile.TemporaryDirectory() as directory:
            path=generate_project(directory,robot,config,12345,'test-token')
            world=path.read_text()
            self.assertEqual(world.count('IndexedFaceSet'),len(robot.assets))
            self.assertIn('normalPerVertex TRUE',world)
            self.assertIn('baseColor 0.42 0.64 0.8',world)
            self.assertNotIn('colorPerVertex',world)
            self.assertNotIn('url [',world)
            self.assertEqual(world.count('HingeJoint {'),4)
            self.assertGreater(collision_body(robot,config)[1][0],.7)

    def test_multiple_components_on_one_link_keep_their_materials(self):
        model=custom_model()
        body=next(l for l in model.links if l.name=='base_link')
        lidar=next(l for l in model.links if l.name=='lidar_link')
        body.parts.extend(lidar.parts);lidar.parts=[];lidar.mass=None
        package=builder_package(model)
        robot=attach_assets(parse_urdf(package['robot_urdf']),{k:MeshAsset.model_validate(v) for k,v in package['robot_assets'].items()})
        from core.simulation.webots_project import visual_shape
        shape=visual_shape(robot,robot.links['base_link'],np.eye(4))
        self.assertEqual(shape.count('IndexedFaceSet'),2)
        self.assertIn('baseColor 0.42 0.64 0.8',shape)
        self.assertIn('baseColor 0.52 0.7 0.56',shape)

    def test_api_setup_save_reopen_and_drive_mesh_robot(self):
        with patch.object(main,'init_rerun'), TestClient(main.app) as client:
            initial=client.get('/api/robot/setup').json()
            response=client.post('/api/model-builder/setup',json=custom_model().model_dump())
            self.assertEqual(response.status_code,200,response.text)
            package=response.json()
            imported=client.post('/api/robot/setup/bundle',files={'file':('robot-model.zip',bundle(custom_model())[0],'application/zip')})
            self.assertEqual(imported.status_code,200,imported.text)
            self.assertEqual(imported.json(),package)
            inspected=client.post('/api/robot/setup/inspect',json=package)
            self.assertEqual(inspected.status_code,200,inspected.text)
            config=inspected.json()['suggested_config']
            config['drive']['wheel_radius']=.12
            draft={**package,'robot_config':config,'name':'Mesh rover','target':'builtin','revision':initial['revision'],'positions':{}}
            checked=client.post('/api/robot/setup/preview',json=draft)
            self.assertEqual(checked.status_code,200,checked.text)
            self.assertIsNone(client.get('/api/project').json()['robot'])
            applied=client.post('/api/robot/setup/apply',json=draft)
            self.assertEqual(applied.status_code,200,applied.text)
            saved=client.post('/api/project/export',json={'name':'Mesh rover','positions':{}}).json()
            self.assertEqual(saved['schema_version'],3)
            self.assertEqual(saved['robot_assets'],package['robot_assets'])
            self.assertEqual(client.post('/api/project/import',json=saved).status_code,200)
            self.assertEqual(client.get('/api/robot/setup').json()['robot_assets'],package['robot_assets'])
            self.assertEqual(ProjectDocument.model_validate(saved).robot_assets,main.runtime.robot.assets)
            received={}
            handle=main.runtime.bus.subscribe('node/sim/out/truth',lambda m:received.update(m.payload))
            try:
                response=client.post('/api/graph/start')
                self.assertEqual(response.status_code,200,response.text)
                main.runtime.graph.update_node_params('drive',{'mode':'manual'})
                keyboard=main.runtime.graph.nodes['keyboard'].node_obj
                keyboard.acquire('mesh-test')
                sequence=0
                deadline=time.monotonic()+5
                while time.monotonic()<deadline and received.get('pose',[0])[0]<.08:
                    keyboard.accept_keys('mesh-test',sequence,['KeyW']);sequence+=1
                    time.sleep(.1)
                keyboard.release('mesh-test')
                self.assertGreater(received.get('pose',[0])[0],.08)
                self.assertFalse([n for n in main.runtime.graph.to_dict()['nodes'] if n['error']])
            finally:
                client.post('/api/graph/stop');handle.close()
            broken=copy.deepcopy(saved);broken['robot_assets'].pop(next(iter(broken['robot_assets'])))
            self.assertEqual(client.post('/api/project/import',json=broken).status_code,400)
            self.assertEqual(client.get('/api/robot/setup').json()['robot_assets'],package['robot_assets'])


if __name__=='__main__':
    logging.disable(logging.INFO)
    unittest.main()
