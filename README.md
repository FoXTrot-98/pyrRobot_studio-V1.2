# PyRobot Studio

A visual robotics workbench using React, FastAPI, Python plugins and ZeroMQ.
It supports visual graphs, headless execution, robot modeling, simulation and
remote project deployment. This is an engineering baseline, not a packaged
desktop release or a hardware-qualified control system.

## Install from a clean checkout

Use 64-bit Python **3.14.6**, Node.js **24.18.0**, npm and Git. Version files
and CI use these versions. Windows is the locally verified platform; Linux has
a CI job but must be verified by a successful run. ARM is not qualified.

From the repository root in PowerShell:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip check
cd frontend
npm.cmd ci
npm.cmd run build
cd ..
```

On Linux, create the environment with `python3.14 -m venv .venv`, use
`.venv/bin/python` instead of the Windows executable, and use `npm`.
The lockfiles pin dependencies; do not substitute `npm install` or the loose
`requirements.txt` when reproducing this baseline. See [baseline verification](docs/BASELINE.md).

## Start Studio

Keep both terminals open. From the repository root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
cd frontend
npm.cmd run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Open **http://127.0.0.1:5173**. Choose **Open project** and select
`examples/four-wheel/navigation.pyrobot.json`, then start the graph.
The built-in simulator needs no physical hardware or Webots installation.
Stop the graph before closing the terminals with Ctrl+C.

## Current capabilities

- Visual plugin graphs, parameter editing, typed message contracts, diagnostics,
  supervised graph lifecycle and a UI-independent headless runtime.
- Plugin SDK, CLI scaffolding and Plugin Builder with subprocess draft tests.
- URDF/Xacro loading, STEP/OBJ Model Builder, assembly frames and joint editing.
  Detailed STEP assemblies are simplified to fit the mesh budget.
- Guided four-wheel robot setup, built-in simulation, Rerun visualization,
  Webots integration, keyboard control, local lidar SLAM and waypoint navigation.
- Model Builder bundles transfer embedded meshes, normals and display colors into
  Robot setup without manually copying mesh files.
- **World setup** in the top bar selects an installed or local Webots world,
  spawn pose and mapping bounds, before or after robot setup. Supported worlds
  are inspected before application; the installed catalog is not a compatibility list.
- A* and Dijkstra planning, proportional and fuzzy path following, frontier
  exploration, return home, and mission pause/cancel controls. Exploration in
  arbitrary unknown environments is not yet qualified.
- Versioned project save/open. Version 4 adds explicit map snapshots and starting-pose confirmation. Version 3 embeds Model Builder meshes, normals
  and display colors; versions 1 and 2 remain readable.
- Authenticated deployment agent with compatibility checks, project transfer,
  remote start/stop, health and logs.

## Model-to-simulation workflow

1. Import STEP/OBJ geometry in Model Builder, arrange frames and joints, and export
   a robot bundle. Alternatively, use a supported URDF or the sample robot.
2. Open **World setup** to choose an external Webots environment if needed. Check
   the world, review the spawn and mapping bounds, then apply it. Changing worlds
   clears saved maps and resets mission settings.
3. Open **Robot setup**, load the robot, assign its four wheels and level lidar/camera
   frames, and check the configuration. Use the Webots target for external worlds.
4. Start the graph in Stop mode. Inspect the spawn and clearance in Webots before
   choosing manual driving or an autonomous mission. Save the project to retain
   the robot and world settings.

External worlds require an installed Webots and supported R2025 ENU (Z-up)
worlds. Studio removes existing top-level robots and inserts the configured robot;
Robot-based actors/devices can also be removed and are listed in the preview.
Original files remain unchanged. Keep referenced world files and assets available
on the backend computer: project JSON does not bundle them. See
[World setup](docs/SIMULATION_WORLDS.md) for supported structures and restrictions.

## Latest verification

The local Windows review of **V1.3.3 (`8deecc8`)**, on **2026-10-01**, passed:

- All 29 regression test scripts, with the documented Windows POSIX serial-test skip.
- Frontend production build and mesh-surface checks.
- Python dependency consistency checks.

Frontend lint completed with three warnings. This review did not repeat a clean
installation or live Webots/browser sessions. Earlier bounded Webots mapping
checks, including delayed scans and car1, are recorded in
[Mapping alignment](docs/MAPPING_ALIGNMENT.md); they do not qualify every world
or physical robot. Webots-dependent unit tests skip when its metadata is unavailable.

A subsequent exploration/contact-model follow-up ran live Webots checks: two
12-second sample-robot exploration/return runs passed, followed by automatic
exploration/return runs for the sample robot and local car1 draft. All reported
zero contacts. See [exploration regression status](docs/SIMULATION_WORLDS.md#exploration-regression-status-2026-10-01)
for physical arrival errors and the distinction from the historical failure.

To run the software checks from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe tests/run_all.py
cd frontend
npm.cmd run build
npm.cmd run lint
node tests/modelSurface.mjs
cd ..
```

The optional car1 STEP input and generated projects are not tracked. Reproducing
that exact integration scenario requires those local files; the regular suite
uses committed fixtures. Remote CI success and a fresh installation of this
revision have not been established by this review.

## Known issues and next priorities

The following issues were identified in the V1.3.3 review and remain open:

- **World dependency validation:** the compatibility hash covers the `.wbt` file,
  not referenced PROTO or geometry contents. A dependency change can therefore
  leave an old saved map apparently compatible. Reapply the world and rebuild
  its map after changing dependencies.
- **Asset parsing:** the importer treats arbitrary quoted strings as possible
  asset paths. For example, a node named `wall.png` can be rejected as a missing
  image even though its name is valid. Asset resolution needs field-aware parsing.
- **Returning to built-in simulation:** Robot setup retains the selected external
  world when choosing the built-in target, which then rejects it. Open a built-in
  example project as a workaround until explicit world clearing is implemented.
- **Exploration recovery:** the historical external-room failure no longer
  reproduced in the latest sample-robot checks, including automatic return home.
  See the world guide for results and stricter regression commands. Escape from
  genuinely obstructed poses and qualification across environments remain unfinished.

Priorities are to fix these workflow issues, qualify exploration and return-home
behavior across environments, expose physical/sensor profiles, and improve
localization confidence and recovery before expanding algorithm choices.

## Guides

| Task | Guide |
| --- | --- |
| Reproduce and verify an installation | [Baseline](docs/BASELINE.md) |
| Understand runtime behavior and limitations | [Runtime contracts](docs/RUNTIME_HARDENING.md) |
| Create plugins | [Plugin Builder](docs/PLUGIN_BUILDER.md) |
| Import CAD and edit robot joints | [Model Builder](docs/ROBOT_MODEL_BUILDER.md) |
| Transfer a model into simulation | [Model to simulation](docs/MODEL_TO_SIMULATION.md) |
| Diagnose mesh/estimated pose and map alignment | [Mapping alignment](docs/MAPPING_ALIGNMENT.md) |
| Select installed or external Webots worlds | [World setup](docs/SIMULATION_WORLDS.md) |
| Configure wheels and sensors | [Robot setup](docs/GUIDED_ROBOT_SETUP.md) |
| Drive and navigate a robot | [Controls and Webots](examples/four-wheel/CONTROLS_AND_WEBOTS.md) |
| Save maps and initialize a new run | [Saved maps](docs/MAP_PERSISTENCE.md) |
| Navigation recovery and autonomy milestones | [Autonomous navigation](docs/AUTONOMOUS_NAVIGATION.md) |
| Try native Webots examples | [Webots examples](examples/webots/README.md) |
| Connect to a deployment agent | [Deployment](docs/ROBOT_DEPLOYMENT.md) |
| Assess hardware/production readiness | [Industrial readiness](docs/INDUSTRIAL_READINESS.md) |
| Choose the next milestone | [Roadmap](docs/ROADMAP.md) |

## Boundaries

Custom drive setup currently supports four-wheel differential robots. CAD
materials/textures and measured mass properties are not imported. Mesh reduction
is approximate. General live transforms and manipulation planning remain future
work. Installed plugins execute in the runtime process; draft subprocess tests
are not a security sandbox. Hardware transports are not verified actuator drivers.

Simulation uses approximate body-box and cylindrical-wheel collisions. Webots
generation currently fixes body mass at 8 kg, wheel mass at 0.3 kg, motor torque
at 8 N m, and uses fixed sensor settings and approximate wheel friction/slip.
These are simulation assumptions, not measured properties of an imported robot.
Generated and imported Webots worlds share their wheel friction/slip defaults in
`core/simulation/wheel_contact.py` to prevent inconsistent tuning.

Webots automatically supplies a gyro without configured noise or bias. When gyro
measurements are present, SLAM uses their integrated heading and corrects only
translation through scan matching. The reviewed navigation path consumes sensor
data, not simulator truth, but idealized heading limits what its mapping results
demonstrate. Real gyro bias handling, loop closure, automatic relocalization and
localization-confidence handling are not implemented. Slopes, stairs and dynamic
scenes are not qualified for this planar navigator.

Projects do not bundle plugin code, Python dependencies, arbitrary external
assets or model weights. Autosave/undo, desktop installation, automatic hardware
profiles, firmware flashing and AI assistance remain unfinished. The optional
`car1` integration fixture is local; the regular suite uses committed examples.
No project license has been selected; redistribution needs a separate review.
