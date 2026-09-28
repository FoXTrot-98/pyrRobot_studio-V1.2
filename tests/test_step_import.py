"""STEP regression tests use the required OCP dependency, never optional CadQuery."""
import math
import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.gp import gp_Trsf, gp_Vec, gp_Ax1, gp_Pnt, gp_Dir
from OCP.TopLoc import TopLoc_Location
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
from OCP.STEPCAFControl import STEPCAFControl_Writer
from OCP.Interface import Interface_Static
from OCP.IFSelect import IFSelect_RetDone
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from core.urdf.cad import detect_step_unit, import_step, _triangulate_shape, _fit_mesh_budget
from core.urdf.builder import bundle, preview, Model
from core.urdf.assets import builder_package


def location(x=0, y=0, z=0, angle=0):
    trsf=gp_Trsf()
    trsf.SetRotation(gp_Ax1(gp_Pnt(0,0,0),gp_Dir(0,0,1)),angle)
    trsf.SetTranslationPart(gp_Vec(x,y,z))
    return TopLoc_Location(trsf)


class StepImportTests(unittest.TestCase):
    def test_unit_detection(self):
        self.assertEqual(detect_step_unit(b"SI_UNIT(.MILLI.,.METRE.)"),(.001,'millimetres'))
        self.assertEqual(detect_step_unit(b"SI_UNIT($,.METRE.)"),(1.,'metres'))

    def test_units_have_identical_physical_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            for unit in ('MM','M','INCH'):
                with self.subTest(unit=unit):
                    writer=STEPControl_Writer()
                    previous=Interface_Static.CVal_s('write.step.unit')
                    try:
                        Interface_Static.SetCVal_s('write.step.unit',unit)
                        writer.Transfer(BRepPrimAPI_MakeBox(100,80,10).Shape(),STEPControl_AsIs)
                        path=Path(tmp)/'box.step'
                        self.assertEqual(writer.Write(str(path)),IFSelect_RetDone)
                        model=import_step(path.read_bytes(),filename=path.name)
                    finally:
                        Interface_Static.SetCVal_s('write.step.unit',previous)
                    self.assertEqual(model.scale,.001)
                    np.testing.assert_allclose(np.ptp(np.asarray(model.parts[0].vertices)*model.scale,axis=0),[.1,.08,.01],atol=1e-9)
                    builder_package(model)  # Same scale survives setup export.

    def test_nested_rotated_and_repeated_assembly_instances(self):
        doc=TDocStd_Document(TCollection_ExtendedString('assembly'))
        tool=XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
        root=tool.NewShape();sub=tool.NewShape()
        shape=tool.AddShape(BRepPrimAPI_MakeBox(10,20,30).Shape(),False)
        def named(label,name):
            TDataStd_Name.Set_s(label,TCollection_ExtendedString(name))
        named(root,'Robot');named(sub,'Subassembly');named(shape,'Block')
        named(tool.AddComponent(sub,shape,location(5,0,0)),'First')
        named(tool.AddComponent(sub,shape,location(30,0,0)),'Second')
        named(tool.AddComponent(root,sub,location(100,0,10,math.pi/2)),'Rotated')
        tool.UpdateAssemblies()
        with tempfile.TemporaryDirectory() as tmp:
            writer=STEPCAFControl_Writer();self.assertTrue(writer.Transfer(doc))
            path=Path(tmp)/'assembly.step';self.assertEqual(writer.Write(str(path)),IFSelect_RetDone)
            model=import_step(path.read_bytes(),filename=path.name)
        self.assertEqual(len(model.parts),2)
        self.assertEqual(sum(l.parent is None for l in model.links),1)
        for name,y in [('First',5),('Second',30)]:
            part=next(p for p in model.parts if p.name==name)
            np.testing.assert_allclose(np.min(part.vertices,axis=0),[80,y,10],atol=1e-8)
            np.testing.assert_allclose(np.max(part.vertices,axis=0),[100,y+10,40],atol=1e-8)
            link=next(l for l in model.links if part.id in l.parts)
            np.testing.assert_allclose(link.xyz,[.1,y*.001,.01],atol=1e-8)
            self.assertAlmostEqual(link.rpy[2],math.pi/2)
        restored=Model.model_validate_json(model.model_dump_json())
        self.assertEqual(restored,model)
        package=builder_package(restored)
        self.assertEqual(len(package['robot_assets']),2)
        self.assertIn('<robot ',bundle(model)[1])

    def test_face_locations_winding_and_normals(self):
        shape=BRepPrimAPI_MakeBox(10,20,30).Shape()
        shape.Location(location(25,0,25,math.pi/2))
        part=_triangulate_shape(shape,np.eye(4),.5,.5,'box','Box')
        points=np.asarray(part.vertices)
        np.testing.assert_allclose(points.min(axis=0),[5,0,25],atol=1e-9)
        np.testing.assert_allclose(points.max(axis=0),[25,10,55],atol=1e-9)
        centre=points.mean(axis=0)
        for face,normals in zip(part.faces,part.normals):
            a,b,c=points[face]
            geometric=np.cross(b-a,c-a);geometric/=np.linalg.norm(geometric)
            self.assertGreater(geometric@((a+b+c)/3-centre),0)
            for normal in normals: self.assertGreater(geometric@normal,.999)

    def test_cylinder_smooth_sides_and_sharp_caps(self):
        part=_triangulate_shape(BRepPrimAPI_MakeCylinder(10,20).Shape(),np.eye(4),.5,.5,'cylinder','Cylinder')
        side_count=0
        for face,normals in zip(part.faces,part.normals):
            points=np.asarray(part.vertices)[face]
            geometric=np.cross(points[1]-points[0],points[2]-points[0]);geometric/=np.linalg.norm(geometric)
            if abs(geometric[2])>.99:
                for n in normals: self.assertGreater(np.dot(n,geometric),.999)
            else:
                side_count+=1
                self.assertGreater(len({tuple(n) for n in normals}),1)
                for point,n in zip(points,normals):
                    radial=np.array([*point[:2],0.]);radial/=np.linalg.norm(radial)
                    self.assertGreater(radial@n,.999)
        self.assertGreater(side_count,0)

    def test_demo_and_invalid_input(self):
        model=import_step((Path(__file__).resolve().parents[1]/'examples/model-builder/step-demo.step').read_bytes())
        self.assertEqual(model.source_format,'step')
        self.assertGreater(len(model.parts),1)
        self.assertIn('x_axis',preview(model)['frames'][0])
        for data,kwargs in [(b'',{}),(b'not STEP',{}),(b'bad',{'deflection':float('nan')}),(b'bad',{'angle':0})]:
            with self.assertRaises(ValueError): import_step(data,**kwargs)

    def test_budget_preserves_components_bounds_and_valid_shading(self):
        cylinder = _triangulate_shape(BRepPrimAPI_MakeCylinder(10,20).Shape(),np.eye(4),.01,.05,'wheel','Wheel')
        box = _triangulate_shape(BRepPrimAPI_MakeBox(5,6,7).Shape(),np.eye(4),.5,.5,'body','Body')
        reduced = _fit_mesh_budget([cylinder, box], 180)
        self.assertEqual([p.id for p in reduced], ['wheel','body'])
        self.assertLessEqual(sum(len(p.faces) for p in reduced),180)
        self.assertEqual(reduced[1],box)
        for original, part in zip([cylinder,box],reduced):
            points=np.asarray(part.vertices)
            np.testing.assert_allclose(points.min(axis=0),np.min(original.vertices,axis=0),atol=.15)
            np.testing.assert_allclose(points.max(axis=0),np.max(original.vertices,axis=0),atol=.15)
            np.testing.assert_allclose(np.linalg.norm(part.normals,axis=2),1,atol=1e-6)
            triangles=points[np.asarray(part.faces)]
            self.assertTrue(np.all(np.linalg.norm(np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]),axis=1)>1e-12))


if __name__=='__main__': unittest.main()
