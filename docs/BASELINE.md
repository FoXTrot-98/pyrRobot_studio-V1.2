# Reproducible engineering baseline

See the [verification record](BASELINE_VERIFICATION.md) for the tested revision, environment, results and known limits.

The root [README](../README.md) is the setup entry point. Feature guides describe
current behavior; old phase labels and version-1-only limitations are not the
current project status. This baseline includes STEP import, assembly placement,
smooth normals, automatic mesh reduction, setup handoff and regression coverage.

## Environment and dependencies

- Python 3.14.6 (64-bit), recorded in `.python-version`.
- Node.js 24.18.0, recorded in `.node-version`; use its bundled npm.
- Python: `requirements.lock.txt`; frontend: `frontend/package-lock.json`.
- Python pins are a tested version snapshot, not hash-verified or offline locks.
- Package caches may be reused, but installed environments and node_modules must
  be created fresh. Network access and available package wheels are required.
- Webots and Microsoft Edge are optional external applications. Browser tests
  use Playwright's `msedge` channel and require Edge. Xacro expansion additionally
  requires the `xacro` executable. None is needed for the core Python/build checks.

CI installs the same Python/Node versions, tests Python on Windows/Linux and
builds/lints the frontend. A configured matrix is not proof that remote jobs passed.

## Clean-checkout verification

Clone the desired commit into a new directory. Do not copy `.venv`, node_modules,
artifacts or local environment files. Follow the installation commands in the
README, then run from the root:

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe tests/run_all.py
.\.venv\Scripts\python.exe -m core.runtime validate examples/four-wheel/navigation.pyrobot.json
.\.venv\Scripts\python.exe -m core.runtime run examples/imu-demo.pyrobot.json --duration 2
cd frontend
npm.cmd run build
npm.cmd run lint
node tests/modelSurface.mjs
cd ..
```

The standalone CLI commands use default broker ports 5555/5556. Stop your other Studio runtime first, or set `PYROBOT_BUS_PUB` and `PYROBOT_BUS_SUB` to separate free loopback endpoints for the CLI process. Do not stop an unrelated running session just to free ports.

The Python runner uses isolated processes and bus ports, with a 60-second limit
per test script. On Windows it reports the expected POSIX pseudo-terminal skip;
serial loopback is still tested. Lint currently reports three warnings in
GridToolbar, useGraph and PluginBuilder; warnings are not build failures.

Run the optional browser check after the Python suite, not concurrently with its timing-sensitive subprocess tests.

Optional browser verification (requires Edge):

```powershell
.\.venv\Scripts\python.exe tests/browser_model_builder.py
```

This verifies STEP/OBJ import, editing, mesh handoff, simulation startup and saved
embedded assets using committed examples. It launches and closes its own servers.
Webots smoke tests require a separately installed Webots application:

```powershell
.\.venv\Scripts\python.exe tests/webots_smoke.py --mesh
```

## Local integration data

`tests/fixtures/car1.STEP` is an optional user-supplied 27 MB assembly, deliberately
not included in the baseline. Generated SDK ZIPs, CAD logs/exports and artifacts
also remain local. The small `examples/model-builder/step-demo.step` is committed
and exercises CAD import without those files.

To reproduce the car1 draft when its source is available locally:

```powershell
.\.venv\Scripts\python.exe tests/car1_workflow.py --import-step
.\.venv\Scripts\python.exe tests/webots_smoke.py --project artifacts/car1/car1-webots.project.json
```

That fixture-specific script estimates wheel size and sensor frames. Its output
is a simulation draft, not real-robot calibration. All generated meshes are
embedded; no manual mesh-file copying is needed.

## Release acceptance

Record the commit ID, OS/tool versions, installation results and check results.
Do not claim Linux/ARM support, hardware qualification, offline reproducibility
or a signed release based only on a Windows development-machine run. No automated
publishing, tagging or deployment is part of this baseline procedure.
