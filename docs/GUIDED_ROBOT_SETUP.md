<!--
SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
SPDX-License-Identifier: Apache-2.0
-->

# Guided robot setup

Restart the backend after installing this update, refresh Studio, and click
**Robot setup** in the top bar. Stop the graph first if it is running.

1. **Robot model:** use the included sample or choose a `.urdf` file. The wizard
   previews box/cylinder visuals at zero joint positions. Rotate the view using
   the slider. Builder meshes use a smooth 3D preview. Open the builder ZIP or use
   **Use in robot setup** from Model Builder to include its meshes. An existing robot is loaded into the draft automatically.
2. **Drive:** confirm the base frame and the two wheel joints on each side.
   Suggestions use wheel geometry, positions and names, so check them carefully.
   Set encoder resolution, robot clearance and planning clearance. Leave the
   radius override empty to use the URDF cylinder radii.
3. **Sensors:** choose the fixed lidar and camera mounting frames. The model's
   transforms supply their offsets; use the camera mounting frame rather than
   its optical frame.
4. **Review:** choose whether to update the current graph or create a built-in /
   Webots simulation project. Click **Check setup**, fix any reported problems,
   then click **Apply robot setup**.

Updating the current graph preserves its nodes, parameters and connections;
simulator base bindings follow the new base-frame selection. Creating a simulation
project builds seven connected nodes: simulator, encoders, SLAM, navigation,
keyboard teleoperation, drive selector and Rerun. The generated project uses the
current reference-room defaults unless an existing configuration is retained.
It starts stopped, with navigation disabled. Select Manual or place waypoints
after starting the graph.

Reviewing a draft does not change the running project or start Webots. Applying
revalidates the draft, rejects stale projects, and leaves the resulting graph
stopped. Replacing a nonempty graph requires a checkbox acknowledgement in the
review screen. **Cancel** discards the draft. **Save project** persists the applied
configuration and embedded URDF.

## Supported robots in this first release

- Four-wheel differential drive, two wheels per side, equal radii and wheel joint
  axes along base +Y.
- Fixed, level camera and lidar mounts.
- For Webots, supported box/cylinder or embedded builder visuals and the installed Webots executable. Custom bodies use a bounding-box collision approximation.
- One connected URDF tree. Export Xacro to URDF before using the wizard.

Physical sensor connections, other drive layouts, editable sensor mounting
positions and generic URDF physics import remain future work. Embedded builder meshes now work in setup and simulation; see [Model to simulation](MODEL_TO_SIMULATION.md).
The wizard configures the existing supported runtime; it does not make arbitrary
robot descriptions automatically simulatable.

## Verification

```powershell
.\.venv\Scripts\python.exe tests/run_all.py
.\.venv\Scripts\python.exe tests/browser_robot_setup.py
```

The optional browser test uses Playwright and Microsoft Edge and starts its own
backend/frontend on separate ports. It checks validation, cancellation, graph
replacement acknowledgement, project creation and startup. Its preview screenshot
is saved to `artifacts/robot-setup-wizard.png`.
