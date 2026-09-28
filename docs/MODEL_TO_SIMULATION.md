# From Model Builder to simulation

Model Builder robots imported from STEP/STP or OBJ can go directly into guided setup, with embedded visual meshes, smooth normals and the builder's component colors. No mesh extraction or manual file copying is needed. This workflow supports four-wheel differential robots, not arbitrary articulated machines.

## Start from CAD

Import STEP/STP in Model Builder, inspect the assembly tree, and define moving joints explicitly. Imported placements remain fixed until you edit them. STEP geometry is normalized to millimetres; mesh deflection is always in millimetres, regardless of the source file units. XYZ axes show link orientation; purple dashed indicators show moving joint axes. Then use the same setup workflow below.

## Try the included mesh robot

1. Open **Model Builder** and use **Open editable model** to load `examples/model-builder/four-wheel-rover.robot-builder.json`.
2. Confirm the scale and root orientation, then click **Use in robot setup**.
3. Inspect the mesh preview. In **Drive**, check the wheel assignments and enter **0.12 m** as the wheel radius override.
4. In **Sensors**, confirm `lidar_link` and `camera_link`.
5. In **Review**, choose **Create built-in simulation project** or **Create Webots simulation project**, then **Check setup**. A Webots installation is required for the latter.
6. Apply the setup. If replacing an existing graph, acknowledge replacement in the review screen. The resulting graph remains stopped.
7. Click **Start Graph**, select **Manual**, and use the keyboard pad. Rerun shows the custom meshes and moving wheels. Webots uses the same custom visuals with its physics engine.
8. **Save project** keeps the URDF and embedded mesh geometry, colors and normals in one `.pyrobot.json`. Opening that project restores the meshes on another compatible installation.

You can also use **Export URDF bundle** in the builder and open that ZIP with **Robot setup → Open Model Builder ZIP**. The ZIP's `robot-builder.json` is the authoritative source: Studio regenerates the link-local mesh geometry from it, preserving smooth normals that STL alone cannot store. ZIPs containing only an arbitrary URDF and mesh files are not supported. Files are read in memory, not extracted to arbitrary paths.

## Preparing your CAD robot

- Import STEP/STP or OBJ, group rigid components into links, and set wheel pivots and joints in Model Builder.
- Use metres after scale calibration. Set the base frame at ground level, +X forward and +Z up.
- Place the four wheel centres one wheel radius above the base frame. Their transformed axes must point along base +Y, with two wheels on each side and equal radii. Enter the measured radius for mesh wheels.
- Give wheel links descriptive names containing `wheel` for automatic suggestions, or select all joints manually.
- Other joints must be fixed. Lidar and camera mounts must have fixed paths from the base and remain level. Empty sensor frames are supported.
- Set robot and planning clearance to cover the actual model. Simplify the CAD export if it exceeds the existing 20,000-triangle budget.

Setup preview and package conversion do not modify the current project. Cancelling discards the draft; applying performs validation again before replacing the stopped graph. Missing meshes and unsupported joint configurations produce errors.

## What is preserved and what is approximated

Geometry, scale, visual transforms, component colors and smooth normals are carried into setup, Rerun and Webots. The builder does not import OBJ materials or textures, so these are the builder's assigned colors, not CAD material finishes. Webots uses separate material shapes for differently colored builder components on one link.

Built-in simulation remains planar and uses the configured circular clearance for collision checks. Webots uses a bounding box around body visuals fixed to the base and cylindrical wheel collisions. Mass and inertia are approximate simulation defaults, not imported CAD dynamics. The body collision box must clear the ground. Neither mode simulates arbitrary suspension, extra actuated joints or mechanical assemblies.

Projects with embedded meshes use schema version 3; existing version 1/2 projects remain readable and mesh-free exports remain version 2. Embedded meshes are capped at 20,000 triangles and 6 MiB of compact asset JSON; builder ZIP upload is capped at 8 MiB. Plugins, Python dependencies, textures, maps and arbitrary external assets are not included. Use a matching Studio/runtime revision when reopening or deploying a version 3 project.

## Verification

- `python tests/test_mesh_workflow.py`: bundle/handoff equality, geometry and normal preservation, invalid assets, material groups, generated Webots geometry, save/reopen, and actual built-in manual motion.
- `python tests/browser_model_builder.py`: direct handoff, cancellation, ZIP import, setup, simulation startup and project save through the browser.
- `python tests/webots_smoke.py --mesh`: real Webots mesh robot, lidar/camera, forward driving, release stop, two waypoints and owned-process cleanup.
