# CAD-first URDF Builder upgrade

This revision changes Model Builder from an OBJ-first manual mesh workflow to a CAD-first workflow.

## Added

- STEP/STP assembly import using Open CASCADE XDE/STEPCAF.
- CAD component hierarchy retained as a robot link tree.
- CAD instance placement retained as the imported link frame pose.
- Open CASCADE unit conversion with millimetre-normalized output and deflection.
- Tessellation controls for mesh deflection and angular detail.
- Full XYZ frame visualization in the 3D preview.
- Bounding-box, CAD-mesh, or no-collision selection per link.
- STEP source metadata retained in the editable robot model.
- STEP importer regression tests and a small CAD assembly example.

## Intentional behavior

The importer does **not** guess revolute/prismatic joints from CAD mates or constraints. Imported relationships are fixed initially so geometry and placement can be inspected first. The user explicitly sets moving joints, axes and limits.

## Dependency

STEP import requires `cadquery-ocp` / Open CASCADE. The dependency is included in `requirements.txt`.

## Verification

`python tests/test_step_import.py` uses Open CASCADE directly, without optional CadQuery or silently skipped tests. It covers millimetre/metre/inch interchange, nested rotated and repeated components, local face placements, reversed faces, smooth cylinder sides, sharp caps, editable-model persistence and setup export.

Run `python tests/run_all.py` for all Python checks, `python tests/browser_model_builder.py` for STEP/OBJ browser workflows and simulation handoff, and `npm run build` plus `npm run lint` in `frontend`.

The Open CASCADE dependency and its installed transitive dependencies are pinned in `requirements.lock.txt`, which is used by CI. Native CAD imports run in a serialized worker thread so they do not execute directly on the HTTP event loop. This is not process isolation or a hard timeout for native CAD operations.
