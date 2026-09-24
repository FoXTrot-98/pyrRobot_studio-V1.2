# Foundation milestone

For the current contract, startup, failure and configuration behavior, see
[the runtime hardening update](RUNTIME_HARDENING.md). New exports use version 2;
the version 1 foundation below remains readable with default robot settings.

The product direction is a cross-platform robotics environment: visual device
configuration, URDF frame bindings, Rerun visualization, Webots simulation,
portable projects, deployment and eventually AI-assisted development.

## Implemented in this milestone

- Version 1 `.pyrobot.json` project files: graph, parameters, plugin versions,
  embedded URDF, link bindings, project name and canvas positions.
- Save/Open Project in Studio. Opening replaces a stopped graph only; validation
  failures preserve the existing graph. Imported projects never auto-start.
- Explicit robot-link selection in the inspector while stopped; bindings must
  reference a link in the loaded robot. Browser refresh restores robot metadata.
- Double-click a wire to disconnect it. Remove Node removes its bridges too.
- Cancellable bus subscriptions and exact matching for node ports.
- ZeroMQ sockets owned by one I/O thread, bounded outgoing queue, logged callback
  errors and bounded WebSocket preview queues. UI previews drop oldest messages
  when overloaded; the outgoing queue raises `queue.Full` at capacity.
- Repeatable node start/stop, worker joins and startup rollback. Parameter values
  and port compatibility are checked on the backend.
- Device parameter updates use restart by default; stopped parameter edits do not
  activate devices. Failed CAN/serial open now fails graph startup.
- Camera synthetic fallback requires `allow_synthetic=true`. Its default is false.
- App shutdown closes graph subscriptions, transport sockets and embedded broker.
- Runtime ownership, graph, plugin discovery and project validation now live in
  `core/runtime`. FastAPI uses that runtime; it is not required for headless runs.
- Command-line project validation and execution, with Ctrl+C/SIGTERM cleanup and
  optional bounded-duration runs. Validation opens no bus sockets or devices.

## Try it

1. Install Python dependencies: `python -m pip install -r requirements.txt`.
2. Run `python -m uvicorn backend.app.main:app --port 8000` from the repository root.
3. In `frontend`, run `npm install` then `npm run dev`.
4. Open `examples/imu-demo.pyrobot.json` with **Open project**.
5. Start the graph, select the IMU and inspect its live readings.
6. Stop, change its robot-link binding, move the nodes and choose **Save project**.
7. Restart the backend and open that file: the configuration is restored stopped.

Save downloads a project document through the browser. It is explicit file-based
persistence, not server-side autosave. Plugins must already be installed with the
recorded versions. Xacro is expanded on upload, so the project stores plain URDF.

## Run without Studio

From the repository root, using the Python environment with dependencies installed:

```sh
python -m core.runtime validate examples/imu-demo.pyrobot.json
python -m core.runtime run examples/imu-demo.pyrobot.json --duration 5
python -m core.runtime run my-robot.pyrobot.json
```

`run` starts the graph; Ctrl+C stops it and releases the bus. `--viz` also starts
Rerun's web viewer. `--plugin-dir PATH` adds a trusted plugin directory. Validation
checks schemas, installed plugin versions, parameters, ports and robot bindings;
it does not verify that physical devices are available. Plugin imports and
constructors run during validation, so plugins must follow the SDK convention of
opening hardware only in `on_start`.

The headless runner and Studio backend each own their local broker. Stop one
before starting the other on the default ports (5555 and 5556). Attaching Studio
to an already-running headless process is a later deployment capability.

## Version 1 boundaries

- External URDF meshes/textures, model weights and plugin source are not bundled.
  File parameters remain references. Copy these dependencies separately until the
  asset packaging milestone; this format is not yet a complete deployment bundle.
- Plugins still execute within one runtime process, whether hosted by FastAPI or
  the headless runner. Process isolation, remote deployment, packaged installation
  and comprehensive crash supervision remain future work.
- PUB/SUB is best effort: startup subscription propagation can lose initial
  messages. There is no reliable-delivery or replay protocol yet.
- Node state/error fields report failures in Studio. The runtime now stops the
  whole graph on reported failures or unexpected worker exit; forcibly isolating
  blocked native drivers still requires future process supervision.
- No hard real-time guarantees or independent actuator watchdogs are provided.
- URDF fixed-joint transforms are implemented and used by the reference robot.
  General live-joint transforms and automatic measurement-frame conversion remain
  future work.
- The [four-wheel reference](../examples/four-wheel/README.md) provides built-in
  and Webots simulation, an embedded Rerun viewport, keyboard teleoperation and
  map-click waypoint missions. See the [controls guide](../examples/four-wheel/CONTROLS_AND_WEBOTS.md).
  Firmware flashing and AI tools are not implemented.

## Next milestones

1. Extend fixed transforms to live joint states and capture-time lookup.
2. Add node health UI, supervised plugin workers and explicit failure policies.
3. Bundle project assets and dependencies; add Rerun and recording UI.
4. Extend the verified Webots reference robot to hardware with identical messages.
5. Add target deployment, board-specific flashing and controlled AI project tools.

## Verification

Run `python tests/run_all.py`. Each script runs in a separate process with a
60-second timeout. The suite includes graph lifecycle, project round trips,
rejected imports, real ZeroMQ routing, backend/WebSocket behavior, virtual CAN,
synthetic camera capture and serial loopback. The POSIX pseudo-terminal test is
explicitly skipped on Windows; serial loopback still runs there.

Frontend checks: `npm run build` and `npm run lint` in `frontend`.
