# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

import io
import math
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET
import zipfile
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.urdf.builder import Model, Link, import_obj, preview, bundle, poses
from core.urdf.model import Origin, origin_matrix
from core.runtime.robot_setup import checked_model

OBJ = '''o body
v 0 0 0
v 2 0 0
v 2 2 0
v 0 2 0
f 1 2 3 4
o arm
v 2 0 0
v 3 0 0
v 2 1 0
f -3 -2 -1
'''


class ModelBuilderTests(unittest.TestCase):
    def test_normals_survive_triangulation_save_and_joint_motion(self):
        text = 'v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nvn 0 0 2\ns off\nf 1//-1 2//-1 3//-1 4//-1'
        model = import_obj(text)
        self.assertEqual(model.parts[0].normals, [[[0,0,1]]*3]*2)
        self.assertEqual(model.parts[0].smoothing, ['off']*2)
        model.links = [Link(name='base_link'), Link(name='arm', parent='base_link', parts=['part_0'], kind='continuous', axis=[1,0,0])]
        restored = Model.model_validate_json(model.model_dump_json())
        moved = preview(restored, {'arm': math.pi/2})
        np.testing.assert_allclose(moved['parts'][0]['normals'][0][0], [0,-1,0], atol=1e-9)
        for invalid in (text.replace('//-1','//0'), text.replace('vn 0 0 2','vn 0 0 0')):
            with self.assertRaises(ValueError): import_obj(invalid)
        old = model.model_dump()
        for part in old['parts']:
            part.pop('normals'); part.pop('smoothing')
        self.assertIsNone(Model.model_validate(old).parts[0].normals)

    def test_obj_groups_loose_parts_negative_indices_and_concave_faces(self):
        model = import_obj(OBJ)
        self.assertEqual(len(model.parts), 2)
        self.assertEqual(len(model.parts[0].faces), 2)
        loose = OBJ.replace('o arm', '# same group')
        self.assertEqual(len(import_obj(loose, True).parts), 2)
        self.assertEqual(len(import_obj(loose, False).parts), 1)
        concave = 'v 0 0 0\nv 2 0 0\nv 2 2 0\nv 1 1 0\nv 0 2 0\nf 1 2 3 4 5'
        part = import_obj(concave).parts[0]
        area = sum(np.linalg.norm(np.cross(np.array(part.vertices[f[1]])-part.vertices[f[0]],np.array(part.vertices[f[2]])-part.vertices[f[0]]))/2 for f in part.faces)
        self.assertAlmostEqual(area, 3)
        for text in ('v nan 0 0\nf 1 1 1', 'v 0 0 0\nf 0 1 2', 'f 1 2 3', ''):
            with self.assertRaises(ValueError): import_obj(text)

    def assembled(self):
        model = import_obj(OBJ)
        model.links = [Link(name='base_link', parts=['part_0']),
                       Link(name='arm_link', parts=['part_1'],parent='base_link',kind='revolute',xyz=[2,0,0],axis=[0,0,2],lower=-math.pi,upper=math.pi,mass=1)]
        return Model.model_validate(model.model_dump())

    def test_fk_and_export_mesh_coordinates(self):
        model = self.assembled()
        moved = preview(model, {'arm_link':math.pi/2})
        np.testing.assert_allclose(moved['parts'][1]['vertices'][1], [2,1,0], atol=1e-9)
        archive, xml, warnings = bundle(model)
        checked_model(xml)
        root = ET.fromstring(xml)
        joint = root.find('joint')
        self.assertEqual(joint.find('origin').get('xyz'), '2 0 0')
        self.assertEqual(joint.find('axis').get('xyz'), '0 0 1')
        self.assertTrue(any('base_link' in w for w in warnings))
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            self.assertEqual(set(z.namelist()), {'robot.urdf','robot-builder.json','README.txt','meshes/base_link.stl','meshes/arm_link.stl'})
            self.assertIn('vertex 1 0 0', z.read('meshes/arm_link.stl').decode())
            restored = Model.model_validate_json(z.read('robot-builder.json'))
            self.assertEqual(restored, model)
        inertial = root.find("link[@name='arm_link']/inertial/inertia")
        self.assertTrue(all(float(inertial.get(k)) > 0 for k in ('ixx','iyy','izz')))

    def test_relative_rotations_root_frame_and_prismatic(self):
        model = self.assembled()
        model.links[0].xyz = [1,2,3]; model.links[0].rpy = [0,0,math.pi/2]
        model.links[1].rpy = [.2,.3,.4]; model.links[1].kind = 'prismatic'
        zero, moved = poses(model, {'arm_link':.3})
        np.testing.assert_allclose(moved['arm_link'][:3,3], zero['arm_link'][:3,3]+zero['arm_link'][:3,2]*.3)
        _,xml,_ = bundle(model)
        origin = ET.fromstring(xml).find('joint/origin')
        actual = origin_matrix(Origin(tuple(map(float,origin.get('xyz').split())),tuple(map(float,origin.get('rpy').split()))))
        np.testing.assert_allclose(actual, np.linalg.inv(zero['base_link']) @ zero['arm_link'],atol=1e-10)

    def test_tree_assignments_limits_and_schema_validation(self):
        model = self.assembled()
        for mutate in (lambda d:d['links'][0].update(parent='arm_link'),
                       lambda d:d['links'][1].update(parts=['part_0']),
                       lambda d:d['links'][1].update(axis=[0,0,0]),
                       lambda d:d['links'][1].update(name='../escape'),
                       lambda d:d['links'][1].update(name='CON'),
                       lambda d:d['links'][1].update(lower=2),
                       lambda d:d['parts'][0]['faces'].append([0,1,999])):
            draft = model.model_dump(); mutate(draft)
            with self.assertRaises(ValueError): Model.model_validate(draft)
        with self.assertRaises(ValueError): preview(model,{'arm_link':99})
        with self.assertRaises(ValueError): preview(model,{'missing':1})


if __name__ == '__main__': unittest.main()
