<!--
SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
SPDX-License-Identifier: Apache-2.0
-->

# Robot Model Builder: CAD assembly to URDF

PyRobot Studio now treats STEP/STP assembly import as the recommended CAD-to-robot workflow. OBJ remains supported for mesh-only fallback imports.

## Recommended workflow

1. Export the robot assembly from CAD as `.step` / `.stp`.
2. Open **Model Builder** and use **Import STEP / STP**.
3. Keep the suggested mesh deflection initially; reduce it when small curved details need more fidelity, or increase it when the CAD is very large.
4. Studio reads the STEP assembly with Open CASCADE, tessellates the solid geometry, and preserves the assembly component hierarchy and instance placements as link frames.
5. Imported components start as **fixed** joints. This is deliberate: STEP assembly placement is reliable geometry/transform data, but PyRobot Studio does not guess revolute/prismatic semantics from CAD constraints.
6. Use the 3D preview to inspect link origins and the XYZ frame axes. Change parent links, joint types, axes, limits, effort and velocity as needed.
7. Validate and export the URDF bundle.

## What STEP fixes compared with OBJ

OBJ is a triangle-mesh interchange format. It does not provide a trustworthy mechanical assembly tree or joint/frame semantics. A STEP assembly keeps CAD solid geometry and component placements, so Studio no longer has to reconstruct the basic component layout from disconnected mesh topology.

The importer still performs tessellation for the interactive preview and URDF mesh assets. Assemblies above 12,000 triangles are simplified component by component, with more detail allocated to larger parts. Components and assembly frames are retained. The builder reports the original and reduced triangle counts; inspect small features after reduction. Unchanged components retain CAD surface normals, while simplified components receive new normals with sharp-edge splitting. The CAD file remains the authoritative geometry source; the editable `pyrobot-model` JSON is the robot-kinematics source after import.

## Units

Open CASCADE reads the STEP unit declarations and converts geometry and placements to millimetres. The editable model uses a scale of 0.001 metres per mesh unit, independent of the source units. Mesh deflection is also measured in millimetres. The source-unit label is informational only; it does not control scaling. Always verify one known dimension before export.

## Frames and joints

The preview shows XYZ axes for every link frame. Moving joint axes are drawn as purple dashed lines alongside the XYZ frame axes. Use the frame display to verify the CAD origin convention before creating moving joints.

Imported assembly relationships become fixed joints initially. Do not treat a CAD mate/constraint as an automatically verified URDF joint. Explicitly set and verify each moving joint's parent, origin and axis.

## Collision geometry

Each link can use **Bounding box**, **CAD mesh**, or **None** for collision. Bounding boxes are cheap and robust. CAD-mesh collision is included in the exported URDF. Studio's current built-in/Webots reference simulators still use their documented circle/box/cylinder approximations; choosing CAD mesh does not enable exact mesh collision physics there.

## Mass and inertia

The builder does not claim CAD material or mass properties automatically. Enter verified mass properties before physics use. The existing fallback inertia calculation is still only a box approximation when a mass is supplied.

## OBJ fallback

OBJ import remains useful for simple mesh-only models. It keeps the original topology-based grouping, smoothing information, and scale calibration tools, but it does not provide the CAD assembly fidelity of STEP import.


## Existing OBJ and simulation workflow

OBJ import still supports object/group labels, loose-component splitting, negative indices, planar polygon triangulation, corner normals and smoothing groups. Scale calibration measures an axis-aligned selection dimension. Camera and selection controls are temporary preview state.

Smooth shading is enabled and wireframe disabled by default. Source normals take priority; without them Studio averages suitable neighboring faces while preserving sharp edges. STEP uses surface-derived corner normals and correctly oriented triangles, retaining smooth curves and sharp caps.

Use **Use in robot setup** for direct handoff, or open the exported Model Builder ZIP in Robot setup. The builder's component colors and normals remain embedded in the saved project. See [Model to simulation](MODEL_TO_SIMULATION.md) for the sample rover, setup steps, supported geometry and test commands.

**Save editable model** preserves geometry and link settings as JSON. Reopen it through **Open editable model** or obtain it from the URDF ZIP. Save before refreshing Studio. Every component must belong to exactly one link; joints must form one connected tree. Revolute and prismatic limits must contain the imported zero pose. Link origins use imported world coordinates; exported URDF origins are calculated relative to each parent.

Limits remain 20,000 triangles per model, 30,000 vertices per component, 128 links and 256 components. STEP upload accepts up to 64 MiB; OBJ accepts up to 4 MiB. Automatic STEP reduction uses a bounded working mesh: up to 200,000 triangles per component and 500,000 per assembly. Exceeding those working limits still requires larger deflection or a simpler CAD assembly. Source CAD materials and textures are not imported.

Verification: `python tests/run_all.py`, `python tests/browser_model_builder.py`, and the frontend build. STEP regression tests directly use the required `cadquery-ocp` dependency, covering physical units, nested/repeated placements, face orientation and curved-surface normals.

To run the browser import test with a specific STEP file, set `PYROBOT_STEP_FIXTURE` to its absolute path before running `tests/browser_model_builder.py`. The later drive test uses the supported sample rover, not the supplied STEP assembly.

For the optional local `tests/fixtures/car1.STEP` fixture, run `python tests/car1_workflow.py --import-step`. It creates an estimated simulation draft under `artifacts/car1`, tests setup, embedded project save/reopen and built-in driving, and exports a Webots project. Then run `python tests/webots_smoke.py --project artifacts/car1/car1-webots.project.json` for real Webots driving and navigation. The draft uses CAD-derived wheel size, CAD -X forward and level test sensors 10 mm outside their housings; verify these against the physical robot before using the configuration elsewhere.
