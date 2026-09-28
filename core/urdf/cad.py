"""CAD assembly import for robot models.

STEP/STP is treated as the primary CAD interchange format. The importer uses
Open CASCADE's XDE/STEPCAF reader to preserve assembly instances and their
placements, tessellating only at the final edge of the import pipeline.

Joint semantics are intentionally not guessed from STEP constraints: the
imported assembly hierarchy becomes a fixed kinematic tree and the user can
change joint type/axis/limits in the Model Builder.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from threading import Lock

import numpy as np

from .builder import Link, Model, Part


def _require_occ():
    try:
        from OCP.BRep import BRep_Tool  # noqa: F401
        from OCP.BRepMesh import BRepMesh_IncrementalMesh  # noqa: F401
        from OCP.STEPCAFControl import STEPCAFControl_Reader  # noqa: F401
        return True
    except Exception as exc:  # pragma: no cover - environment-dependent
        raise ValueError(
            "STEP import requires the Open CASCADE Python package "
            "(cadquery-ocp). Install the project's requirements and restart Studio."
        ) from exc


def detect_step_unit(data: bytes) -> tuple[float, str]:
    """Return metres per STEP length unit and a human-readable label.

    STEP files commonly carry an explicit SI unit declaration. We recognize
    the common metre/centimetre/millimetre/micrometre and inch/foot forms. When
    no recognizable declaration is found, STEP's usual CAD convention of mm is
    used as a conservative default and reported to the caller.
    """
    text = data[:2_000_000].decode("latin-1", errors="ignore").upper()
    compact = re.sub(r"\s+", "", text)
    if "SI_UNIT(.MILLI.,.METRE.)" in compact or "SI_UNIT($,.MILLI.,.METRE.)" in compact:
        return 0.001, "millimetres"
    if "SI_UNIT(.CENTI.,.METRE.)" in compact:
        return 0.01, "centimetres"
    if "SI_UNIT(.MICRO.,.METRE.)" in compact:
        return 1e-6, "micrometres"
    if "SI_UNIT($,.METRE.)" in compact or "SI_UNIT(,.METRE.)" in compact:
        return 1.0, "metres"
    if "'INCH'" in compact or "'INCHES'" in compact:
        return 0.0254, "inches"
    if "'FOOT'" in compact or "'FEET'" in compact:
        return 0.3048, "feet"
    return 0.001, "millimetres (assumed)"


def _safe_name(value: str, fallback: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_]", "_", (value or "").strip())
    value = re.sub(r"_+", "_", value).strip("_")
    if not value:
        value = fallback
    if not re.match(r"^[A-Za-z]", value):
        value = f"link_{value}"
    return value[:64]


def _unique_name(name: str, used: set[str]) -> str:
    base = _safe_name(name, "link")
    candidate = base
    index = 2
    while candidate.lower() in {u.lower() for u in used}:
        suffix = f"_{index}"
        candidate = f"{base[:64-len(suffix)]}{suffix}"
        index += 1
    used.add(candidate)
    return candidate


def _trsf_matrix(trsf) -> np.ndarray:
    matrix = np.eye(4)
    for row in range(1, 4):
        for col in range(1, 4):
            matrix[row - 1, col - 1] = float(trsf.Value(row, col))
    trans = trsf.TranslationPart()
    matrix[:3, 3] = [float(trans.X()), float(trans.Y()), float(trans.Z())]
    return matrix


def _label_name(label, fallback: str) -> str:
    try:
        from OCP.TDataStd import TDataStd_Name
        name = TDataStd_Name()
        if label.FindAttribute(TDataStd_Name.GetID_s(), name):
            value = name.Get().ToExtString().strip()
            if value:
                return value
    except Exception:
        pass
    return fallback


def _children(shape_tool, label, recursive=False):
    from OCP.XCAFDoc import XCAFDoc_ShapeTool
    from OCP.TDF import TDF_LabelSequence

    sequence = TDF_LabelSequence()
    if not XCAFDoc_ShapeTool.GetComponents_s(label, sequence, recursive):
        return []
    return [sequence.Value(i) for i in range(1, sequence.Length() + 1)]


def _reference_label(label):
    from OCP.XCAFDoc import XCAFDoc_ShapeTool
    from OCP.TDF import TDF_Label

    reference = TDF_Label()
    if XCAFDoc_ShapeTool.GetReferredShape_s(label, reference):
        return reference
    return None


def _shape_for_label(shape_tool, label):
    from OCP.XCAFDoc import XCAFDoc_ShapeTool
    return XCAFDoc_ShapeTool.GetShape_s(label)


def _rpy_from_matrix(matrix: np.ndarray) -> list[float]:
    pitch = math.asin(float(np.clip(-matrix[2, 0], -1, 1)))
    if abs(math.cos(pitch)) > 1e-8:
        return [
            math.atan2(float(matrix[2, 1]), float(matrix[2, 2])),
            pitch,
            math.atan2(float(matrix[1, 0]), float(matrix[0, 0])),
        ]
    return [0.0, pitch, math.atan2(float(-matrix[0, 1]), float(matrix[1, 1]))]


def _triangulate_shape(shape, global_matrix: np.ndarray, deflection: float, angle: float, part_id: str, part_name: str, *, raw: bool = False) -> Part:
    from OCP.BRep import BRep_Tool
    from OCP.BRepLib import BRepLib_ToolTriangulatedShape
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from OCP.TopLoc import TopLoc_Location

    if shape.IsNull():
        raise ValueError(f"CAD component '{part_name}' contains no shape")
    BRepMesh_IncrementalMesh(shape, float(deflection), False, float(angle), True)
    vertices, faces, normals = [], [], []
    vertex_lookup = {}

    def add_vertex(xyz):
        key = tuple(round(float(v), 9) for v in xyz)
        if key not in vertex_lookup:
            vertex_lookup[key] = len(vertices)
            vertices.append(xyz.tolist())
        return vertex_lookup[key]

    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, location)
        if triangulation is not None and triangulation.NbTriangles() > 0:
            transform = global_matrix @ _trsf_matrix(location.Transformation())
            normal_transform = np.linalg.inv(transform[:3,:3]).T
            BRepLib_ToolTriangulatedShape.ComputeNormals_s(face, triangulation)
            reversed_face = face.Orientation() == TopAbs_REVERSED
            for triangle_index in range(1, triangulation.NbTriangles() + 1):
                tri = triangulation.Triangle(triangle_index)
                node_ids = [tri.Value(1), tri.Value(2), tri.Value(3)]
                if reversed_face != (np.linalg.det(transform[:3,:3]) < 0):
                    node_ids[1], node_ids[2] = node_ids[2], node_ids[1]
                points = []
                for node in node_ids:
                    point = triangulation.Node(node)
                    points.append((transform @ [point.X(),point.Y(),point.Z(),1.])[:3])
                face_normal = np.cross(points[1]-points[0],points[2]-points[0])
                length = np.linalg.norm(face_normal)
                if length < 1e-15:
                    continue
                face_normal /= length
                corner_normals = []
                for node in node_ids:
                    if triangulation.HasNormals():
                        n = triangulation.Normal(node)
                        normal = normal_transform @ [n.X(),n.Y(),n.Z()]
                        normal /= np.linalg.norm(normal)
                        # OCC may supply orientation-adjusted normals. Align
                        # with the final winding without flipping them twice.
                        if normal @ face_normal < 0: normal = -normal
                    else:
                        normal = face_normal
                    corner_normals.append(normal.tolist())
                indices = [add_vertex(point) for point in points]
                if len(set(indices)) != 3: continue
                faces.append(indices)
                normals.append(corner_normals)
                if len(faces) > (200000 if raw else 20000) or len(vertices) > (300000 if raw else 30000):
                    raise ValueError(f"STEP component '{part_name}' is too detailed; increase mesh deflection or simplify it")
        explorer.Next()
    if not faces:
        raise ValueError(f"CAD component '{part_name}' could not be tessellated")
    factory = Part.model_construct if raw else Part
    return factory(id=part_id,name=part_name,vertices=vertices,faces=faces,normals=normals,smoothing=['step']*len(faces))


def _fit_mesh_budget(parts: list[Part], budget: int = 12000) -> list[Part]:
    """Reduce each component independently, never merging assembly instances.

    Leave headroom for the embedded asset byte limit as well as triangle limits.
    Native CAD normals survive unchanged on components that need no reduction.
    """
    total = sum(len(p.faces) for p in parts)
    if total <= budget:
        return [Part.model_validate(p.model_dump()) for p in parts]
    from vtkmodules.vtkCommonCore import vtkPoints
    from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
    from vtkmodules.vtkFiltersCore import vtkQuadricDecimation, vtkPolyDataNormals
    from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy

    minimum = [min(96, len(p.faces)) for p in parts]
    if sum(minimum) > budget:
        minimum = [min(12, len(p.faces)) for p in parts]
    available = budget - sum(minimum)
    if available < 0:
        raise ValueError('Too many STEP components for the mesh budget')
    # Screen-sized mechanical parts deserve more detail than tiny electronics,
    # even when the electronics contain many more CAD faces.
    weights = [math.sqrt(max(0, len(p.faces) - n)) *
               float(np.linalg.norm(np.ptp(np.asarray(p.vertices), axis=0)))
               for p, n in zip(parts, minimum)]
    weight_sum = sum(weights)
    result = []
    for part, floor, weight in zip(parts, minimum, weights):
        target = min(len(part.faces), floor + int(available * weight / weight_sum))
        if len(part.faces) <= target:
            result.append(Part.model_validate(part.model_dump()))
            continue
        points = vtkPoints()
        points.SetData(numpy_to_vtk(np.asarray(part.vertices, dtype=np.float64), deep=True))
        cells = vtkCellArray()
        for face in part.faces:
            cells.InsertNextCell(3)
            for index in face:
                cells.InsertCellPoint(index)
        mesh = vtkPolyData()
        mesh.SetPoints(points)
        mesh.SetPolys(cells)
        decimator = vtkQuadricDecimation()
        decimator.SetInputData(mesh)
        decimator.SetTargetReduction(1 - max(1, target - 2) / len(part.faces))
        decimator.Update()
        output = decimator.GetOutput()
        if not 0 < output.GetNumberOfPolys() <= target:
            raise ValueError(f"Cannot simplify '{part.name}' within the mesh budget; simplify this component in CAD")
        shading = vtkPolyDataNormals()
        shading.SetInputData(output)
        shading.SetFeatureAngle(45)
        shading.SplittingOn()
        shading.ConsistencyOn()
        shading.Update()
        output = shading.GetOutput()
        vertices = vtk_to_numpy(output.GetPoints().GetData())
        faces = vtk_to_numpy(output.GetPolys().GetConnectivityArray()).reshape(-1, 3)
        normals = vtk_to_numpy(output.GetPointData().GetNormals())
        result.append(Part(id=part.id, name=part.name, vertices=vertices.tolist(),
                           faces=faces.tolist(), normals=normals[faces].tolist(),
                           smoothing=['step'] * len(faces)))
    return result


_IMPORT_LOCK = Lock()


def import_step(data: bytes, *, filename: str = "robot.step", deflection: float = 0.5, angle: float = 0.5) -> Model:
    # OCC has process-wide configuration; serialize CAD imports in the worker pool.
    with _IMPORT_LOCK:
        return _import_step(data, filename=filename, deflection=deflection, angle=angle)


def _import_step(data: bytes, *, filename: str = "robot.step", deflection: float = 0.5, angle: float = 0.5) -> Model:
    """Import a STEP/STP assembly into the editable Robot Model format.

    The returned model preserves assembly instance placement as link-frame
    transforms and creates fixed joints for the imported assembly hierarchy.
    Users can then change joint semantics without losing CAD geometry.
    """
    _require_occ()
    if not data:
        raise ValueError("STEP file is empty")
    if len(data) > 64 * 1024 * 1024:
        raise ValueError("STEP file exceeds 64 MiB")
    if not (0.01 <= deflection <= 50.0):
        raise ValueError("STEP mesh deflection must be between 0.01 and 50 millimetres")
    if not (0.01 <= angle <= math.pi):
        raise ValueError("STEP mesh angle must be between 0.01 and pi radians")

    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TDocStd import TDocStd_Document
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDF import TDF_LabelSequence
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    _, unit_name = detect_step_unit(data)
    source_scale = 0.001  # OCC output is explicitly normalized to millimetres.
    # STEPCAFControl currently works reliably with a filesystem path; keep the
    # temporary file scoped to the request and never expose it to the project.
    import tempfile
    with tempfile.TemporaryDirectory(prefix="pyrobot-step-") as directory:
        path = Path(directory) / "input.step"
        path.write_bytes(data)
        reader = STEPCAFControl_Reader()
        reader.SetColorMode(True)
        reader.SetNameMode(True)
        reader.SetLayerMode(True)
        status = reader.ReadFile(str(path))
        from OCP.IFSelect import IFSelect_RetDone
        if status != IFSelect_RetDone:
            raise ValueError(f"Open CASCADE could not read '{filename}'")
        document = TDocStd_Document(TCollection_ExtendedString("PyRobotSTEP"))
        XCAFDoc_DocumentTool.SetLengthUnit_s(document, source_scale)
        reader.ChangeReader().SetSystemLengthUnit(1.0)  # millimetres
        if not reader.Transfer(document):
            raise ValueError(f"Open CASCADE could not transfer '{filename}'")

        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
        free = TDF_LabelSequence()
        shape_tool.GetFreeShapes(free)
        if free.Length() == 0:
            raise ValueError("STEP contains no free assembly shapes")

        parts: list[Part] = []
        links: list[Link] = []
        used_links: set[str] = set()
        used_parts = 0

        def add_link(raw_name: str, parent: str | None, world: np.ndarray, part_ids: list[str] | None = None) -> str:
            name = _unique_name(raw_name, used_links)
            xyz = [float(v) for v in world[:3, 3] * source_scale]
            links.append(Link(name=name, parent=parent, parts=part_ids or [], kind='fixed', xyz=xyz, rpy=_rpy_from_matrix(world)))
            return name

        def visit(label, parent_link, parent_world, fallback):
            nonlocal used_parts
            if len(links) >= 128:
                raise ValueError('STEP assembly exceeds 128 links; simplify the assembly')
            reference = _reference_label(label)
            ref = reference if reference is not None else label
            local = _trsf_matrix(shape_tool.GetLocation_s(label).Transformation())
            world = parent_world @ local
            if reference is not None:
                world = world @ _trsf_matrix(shape_tool.GetLocation_s(ref).Transformation())
            display_name = _label_name(label, _label_name(ref, fallback))
            if re.fullmatch(r'NAUO\d+', display_name, re.IGNORECASE):
                display_name = _label_name(ref, display_name)
            link_name = add_link(display_name, parent_link, world)
            children = _children(shape_tool, ref, False)
            if children:
                for index, child in enumerate(children,1):
                    visit(child,link_name,world,f'component_{index}')
            else:
                from OCP.TopLoc import TopLoc_Location
                # The top-level location is already in world. Keep nested face
                # locations, but do not apply the definition placement twice.
                shape = _shape_for_label(shape_tool,ref).Located(TopLoc_Location())
                part = _triangulate_shape(shape,world,deflection,angle,f'part_{used_parts}',display_name,raw=True)
                parts.append(part)
                links[-1].parts = [part.id]
                used_parts += 1
                if sum(len(p.faces) for p in parts) > 500000:
                    raise ValueError('STEP assembly exceeds the 500,000-triangle working limit; increase deflection or simplify it')
            return link_name

        if free.Length() == 1:
            visit(free.Value(1),None,np.eye(4),'base_link')
        else:
            root_link = add_link('base_link',None,np.eye(4))
            for index in range(1,free.Length()+1):
                visit(free.Value(index),root_link,np.eye(4),f'component_{index}')

    if not parts:
        raise ValueError("STEP assembly was read, but no tessellatable components were found")
    original_triangles = sum(len(p.faces) for p in parts)
    parts = _fit_mesh_budget(parts)
    model = Model(name=_safe_name(Path(filename).stem, "robot"), scale=source_scale, parts=parts, links=links)
    if original_triangles > 12000:
        model.import_notes = [f'Geometry simplified from {original_triangles:,} to {sum(len(p.faces) for p in parts):,} triangles. All components and assembly frames retained; inspect small features before use.']
    model.source_format = 'step'
    model.source_name = filename[:200]
    model.source_unit = unit_name[:40]
    return model
