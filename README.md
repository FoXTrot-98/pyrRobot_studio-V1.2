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
- Versioned project save/open. Version 4 adds explicit map snapshots and starting-pose confirmation. Version 3 embeds Model Builder meshes, normals
  and display colors; versions 1 and 2 remain readable.
- Authenticated deployment agent with compatibility checks, project transfer,
  remote start/stop, health and logs.

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

Projects do not bundle plugin code, Python dependencies, arbitrary external
assets or model weights. Autosave/undo, desktop installation, automatic hardware
profiles, firmware flashing and AI assistance remain unfinished. The optional
`car1` integration fixture is local; the regular suite uses committed examples.
No project license has been selected; redistribution needs a separate review.
