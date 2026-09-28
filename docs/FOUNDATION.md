# Runtime foundation

For installation and current capabilities, start with the [README](../README.md).
For fresh-install acceptance checks, use [Baseline verification](BASELINE.md).

The backend and CLI share `core/runtime`: plugin discovery, graph lifecycle,
project validation and execution do not require the Studio UI. Project imports
validate a stopped candidate before replacing the current graph and never start
it automatically. Version 1 and 2 projects remain readable; version 3 embeds
Model Builder meshes, normals and display colors.

```powershell
.\.venv\Scripts\python.exe -m core.runtime validate examples/imu-demo.pyrobot.json
.\.venv\Scripts\python.exe -m core.runtime run examples/imu-demo.pyrobot.json --duration 5
```

The runtime owns its broker. Avoid running multiple default runtime instances on
the same ports. Headless validation checks software configuration, not physical
device availability. Plugins are trusted Python code; their imports and
constructors run during validation.

See [runtime contracts](RUNTIME_HARDENING.md) for message schemas, startup
readiness, failure supervision and configuration. See [deployment](ROBOT_DEPLOYMENT.md)
for the separate authenticated agent, and [industrial readiness](INDUSTRIAL_READINESS.md)
for outstanding isolation, hardware and production work.

Explicit project saving is implemented; project autosave and undo/redo are not.
Plugin code, dependencies and arbitrary external files remain outside project
JSON. Timeline recording/replay classes exist, but a Studio timeline workflow is
not integrated. The [roadmap](ROADMAP.md) replaces the earlier phase checklist.
