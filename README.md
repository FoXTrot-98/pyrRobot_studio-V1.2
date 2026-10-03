<!--
SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
SPDX-License-Identifier: Apache-2.0
-->

# PyRobot Studio

Originally created by **Kanishka Kularathna ([FoXTrot-98](https://github.com/FoXTrot-98))**.
Community contributions are welcome. Project-owned material is licensed under
[Apache 2.0](LICENSE); see [NOTICE](NOTICE), [authors](AUTHORS.md) and
[third-party notices](THIRD_PARTY_NOTICES.md).

To report a bug or propose an improvement, read [CONTRIBUTING.md](CONTRIBUTING.md).

A visual robotics workbench using React, FastAPI, Python plugins and ZeroMQ.
It supports visual graphs, headless execution, robot modeling, simulation and
remote project deployment. This is an engineering baseline, not a packaged
desktop release or a hardware-qualified control system.

## Install from a clean checkout

**New to Studio?** Start with the [visual getting-started PDF](docs/getting-started/PyRobot-Studio-Getting-Started.pdf).
Its 11 illustrated pages cover your own robot, world placement, first drive,
navigation and saving. An [offline HTML edition](docs/getting-started/index.html)
is also included.

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
  are inspected before application. With a robot configured, a motor-disabled
  Webots preview validates physical placement and sensor readiness before Apply.
  A cancellable nearby-position search can suggest a physically supported spawn;
  you inspect, adopt and recheck it before applying.
  The installed catalog is not a compatibility list.
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
4. With the robot configured, reopen **World setup** and **Check world**. Inspect
   the actual world in Webots and correct the numeric placement until valid.
   Apply, then start the graph in Stop mode. Startup repeats placement and sensor checks before
   choosing manual driving or an autonomous mission. Save the project to retain
   the robot and world settings.

External worlds require an installed Webots and supported R2025 ENU (Z-up)
worlds. Studio removes existing top-level robots and inserts the configured robot;
Robot-based actors/devices can also be removed and are listed in the preview.
Original files remain unchanged. Keep referenced world files and assets available
on the backend computer: project JSON does not bundle them. See
[World setup](docs/SIMULATION_WORLDS.md) for supported structures and restrictions.

## Latest verification

The validation and nearby-placement milestone on **2026-10-03** passed all **32 regression scripts**,
with the documented Windows serial-test skip, plus the focused old-project
migration regression and licensing checks. Live Webots checks passed sample-robot
manual driving, two waypoints and return home with zero contacts; car1 passed
invalid-placement rejection, settled-pose adoption, apply and sensor startup in
`complete_apartment.wbt`. Starting at the failing origin in that world, the nearby
search found a supported car1 position on attempt four; a fresh placement check,
apply and sensor startup passed. The browser workflow passed search, adoption,
rechecking and apply. Frontend build passed; lint reported three existing warnings.
These are bounded checks, not arbitrary-world or hardware
qualification. A clean installation was not repeated for this milestone.

The configurable-physics follow-up also passed all 32 regression scripts, the
frontend build, licensing checks and browser apply/persistence/cancel checks.
Live Webots placement, nearby search, adoption and rechecking passed in the
external-room fixture with a 9.5 kg body and 12 rad/s motor limit. This verifies
configuration and placement, not calibrated dynamics or navigation accuracy.

The subsequent two-world route check passed manual driving, two spawn-relative
waypoints and return home with zero reported contacts in both worlds. Physical
home error was 0.152 m in the generated room and 0.081 m in the imported-room
fixture starting at `(1, -1, pi/2)`. These are single-run measurements, not
repeatability bounds. Run `tests/webots_matrix.py` to reproduce the cases and
retain individual logs and measurements; see [world validation](docs/SIMULATION_WORLDS.md#reproduce-checks).

Car1 then passed two 12-simulation-second exploration/return checks in each of
the external-room fixture and installed `complete_apartment.wbt` (four runs,
zero reported contacts). Physical home errors were 0.087–0.116 m and
0.149–0.188 m respectively. These short runs use an explicit return request;
they do not establish complete apartment coverage or blocked-route recovery.

The obstruction-recovery follow-up fixed a false `stalled` result while waiting
with zero commanded motion. The progress timer now pauses during blockage while
retaining previous unproductive driving time. All 33 regression scripts passed;
the final timer change also passed 12 focused recovery tests plus exploration
and mission-management checks. These use deterministic obstacle/map inputs;
live moving-obstacle recovery in Webots remains unqualified.

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

The validation follow-up adds geometry-based clearance checks, an eight-second
startup settling deadline, and first-sample encoder/gyro baselines. The sample
robot's clearance default is now 0.55 m. Older projects with smaller clearance
values must be corrected in Robot setup; the error reports the required minimum.
Use **Update robot in current graph** to apply a clearance correction even when
the world hash is stale. The warning remains and graph startup stays blocked
until the subsequent World setup check is applied.

World compatibility now includes explicit local URL dependency contents, including
nested local PROTOs and their directly referenced meshes/textures. Old world hashes
must be refreshed with **World setup → Check world → Apply world**; this resets
saved maps and missions. Asset resolution examines URL fields, so ordinary names
such as `wall.png` are preserved.

Remaining limitations:

- **World dependency validation:** remote assets, template-generated paths,
  custom PROTO parameter indirection and mesh-internal references are not fully
  content-locked. Keep these dependencies fixed and reapply/rebuild maps after
  changing them. This is not a complete Webots asset packager.
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
physics can be configured in **Robot setup → Drive → Webots physics**: body mass,
mass per wheel, motor torque/speed limits, joint damping, friction and slip.
Old projects retain defaults of 8 kg body mass, 0.3 kg per wheel and 8 N m torque.
Sensor settings remain fixed; inertia and wheel contact behavior are approximate.
These are simulation assumptions, not measured properties of an imported robot.
Generated and imported Webots worlds share their wheel friction/slip defaults in
`core/simulation/wheel_contact.py` to prevent inconsistent tuning.
The saved physics settings apply to both kinds of world; the built-in geometric
simulator does not model these forces. See [physics settings](docs/SIMULATION_WORLDS.md#robot-physics).

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
Project-owned files use Apache-2.0. Bundled third-party material retains its own
notices; external assets and installed dependencies are not relicensed. See
[licensing scope and file coverage](docs/LICENSING.md) before packaging a distribution.
