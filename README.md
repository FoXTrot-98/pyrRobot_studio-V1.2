# PyRobot Studio

A visual robotics workbench built with React, FastAPI, Python plugins and ZeroMQ.
The goal is a cross-platform robotics platform with Rerun, Webots, portable robot
projects, target deployment and AI-assisted development.

**Try the [four-wheel simulation project](examples/four-wheel/README.md):**
URDF robot, lidar, camera, encoders, local SLAM, A* navigation and embedded Rerun.
The [keyboard, waypoint and Webots examples](examples/four-wheel/CONTROLS_AND_WEBOTS.md)
add manual driving, map-selected missions and actual Webots wheel physics.

**New: [guided robot setup](docs/GUIDED_ROBOT_SETUP.md).** Click **Robot setup** to
preview a URDF, assign wheels and sensor frames, validate the configuration and
create a wired simulation project without editing JSON.

**[Native Webots robot examples](examples/webots/README.md):** choose **Examples**
to open a Panda arm, NAO humanoid or KUKA youBot with the original Webots world,
Studio action controls and Rerun joint telemetry.

**[Robot connection and deployment](docs/ROBOT_DEPLOYMENT.md):** use **Deploy**
to connect to an authenticated robot agent, check and transfer a project, and
start/stop its graph or inspect health and logs remotely.

**Current milestone:** a runnable reference robot, versioned project save/load,
and a UI-independent runtime with headless project validation and execution.
The [runtime hardening guide](docs/RUNTIME_HARDENING.md) describes typed messages,
startup readiness, node health, preserved capture timestamps and configurable
robot/environment/map settings, including version 1 project migration.
See [the foundation guide](docs/FOUNDATION.md) for setup, a runnable example,
verification, limitations and the next milestones.

The historical phase notes below describe the earlier prototype. Where they
conflict with the foundation guide, use the guide. In particular, the embedded
Rerun viewport is available for the reference simulation; general live-joint
transforms remain unfinished. Camera fallback now
requires explicit opt-in, and project files do not yet bundle external assets.

---

# PyRobot Studio — Ground-Up Rebuild

Status: **Phase 1-4 complete** — bus, PRT timing, plugin SDK, URDF engine,
FastAPI backend, React Studio UI, Rerun 3D/SLAM viz, real device plugins
(camera, CAN, serial), a processing node, and CLI plugin scaffolding —
all tested end-to-end, including deliberately-triggered failure paths.

## What's built and tested right now

### 1. Message Bus (`core/bus/`)
- `broker.py` — standalone ZeroMQ XSUB/XPUB proxy. This is the actual hub;
  every node connects to it (never binds directly to each other). Run it
  standalone with `python -m core.bus.broker`, or embed it in the backend
  process at startup.
- `base.py` — `Bus` / `BusTransport` / `ZmqTransport`. Plugin code only ever
  talks to `Bus.publish()` / `Bus.subscribe()` — the transport is swappable
  (LCM adapter can be dropped in later for topics that need it, same hybrid
  approach as V3).
- ✅ Verified: real broker, real publisher, real subscriber, 100Hz stream,
  zero drops, correct topic routing (`tests/test_bus_integration.py`).

### 2. PRT — PyRobot Time (`core/timing/`)
- `clock.py` — `PRTClock` (per-node, stamps at capture time) + `ClockAuthority`
  (one per session, broadcasts sync beacons other nodes discipline to).
  Inspired by SMPTE's idea of a genlock time authority, but rate-agnostic
  (no fixed 24/30fps assumption) since different sensors run at wildly
  different Hz.
  - ✅ Verified: monotonic stamping, correct sequence counting, discipline
    offset correction, SMPTE-style `HH:MM:SS:FF` display labels.
- `timeline.py` — `TimelineRecorder` / `TimelinePlayer`. Records every bus
  message to a flat log + sqlite seek index; supports scrub/seek, variable-
  speed replay, and topic-filtered playback.
  - ✅ Verified: record 5 messages → close → reopen → seek/read back
    byte-identical payloads → full playback in original order.

### 3. Plugin SDK (`sdk/pyrobot_plugin/`)
- `manifest.py` — `PluginManifest`, `PortSpec`, `ParamSpec`. Fully
  introspectable — this is what will let the Studio UI auto-generate node
  cards and property panels with zero per-plugin frontend code.
- `node.py` — `Node` base class. Subclass it, declare a `manifest`,
  implement `on_start` / `on_message`, call `self.emit(...)`. Bus wiring,
  topic naming, and lifecycle are handled for you.
- `plugins/examples/fake_imu.py` — a real working example plugin (~30
  lines) proving the SDK surface is usable.

### 4. URDF Engine (`core/urdf/`)
- `model.py` — parses `.urdf` (and `.xacro` via the `xacro` CLI) into a
  `RobotModel`: links, joints, mount origins, joint limits, kinematic-tree
  queries (`path_to_root`, `static_transform` for fixed-joint offsets).
  This becomes the source of truth plugins query instead of hand-written
  YAML — a plugin with `requires_urdf_link=True` gets offered real link
  names from the loaded robot.
  - ✅ Verified against a sample 3-link robot: correct link/joint parsing,
    correct kinematic chain resolution, correctly refuses to compute a
    static transform through a non-fixed joint.

### 5. Backend (`backend/app/`) — NEW in Phase 2
- `plugin_registry.py` — scans a directory for `Node` subclasses and builds
  the `manifest.id -> class` registry (no manual registration; drop a file
  in `plugins/`, restart, it's discoverable).
- `graph.py` — `NodeGraph`: instantiates nodes from the registry, and wires
  connections between them as bus-level bridges (subscribes to node A's
  output topic, republishes onto node B's input topic) — so individual
  plugins stay unaware of graph topology.
- `main.py` — FastAPI app: `/api/plugins`, `/api/robot/urdf` (upload +
  parse), `/api/graph/*` (add/remove nodes, connect ports, start/stop),
  and a `/ws/bus` WebSocket streaming every live bus message to a client
  (this is what the future Studio UI will animate the node graph from).
  - ✅ Verified end-to-end over real HTTP + WebSocket: plugin discovery,
    URDF upload, rejecting an unbound `requires_urdf_link` node (400),
    rejecting an unknown plugin id (404), starting a graph and receiving
    >5 live messages over the websocket, and — critically — a real
    node-to-node **connection** test proving messages published on one
    node's output port are correctly bridged onto another node's input
    port (`tests/test_backend.py`).
- Explore it yourself: `uvicorn backend.app.main:app --port 8000`
  then open `http://localhost:8000/docs` for the interactive Swagger UI —
  see the included PDF testing guide for a full walkthrough.

### 6. Frontend (`frontend/`) — NEW in Phase 3
Real Vite + React 19 + TypeScript app, using React Flow for the node canvas.
Design system is the Neomorphism direction validated as a standalone mockup
first (soft embossed panels, same-color-as-background cards, port jacks,
rationed accent color) — see `frontend/src/styles/tokens.css` for the exact
tokens carried over.

- `components/TopBar.tsx` — brand, URDF upload (drives `/api/robot/urdf`),
  a live PRT timecode readout (`utils/prt.ts` mirrors the backend's
  `frame_label` formatting) fed by the bus WebSocket, and the Start/Stop
  Graph control wired to `/api/graph/start` / `/stop`.
- `components/Palette.tsx` — searchable, category-grouped, fetched live
  from `/api/plugins`; collapsible per the earlier UI feedback.
- `components/StudioNode.tsx` — the custom React Flow node renderer. Ports
  are real React Flow `Handle`s (draggable, connectable) styled as the
  neomorphic jacks from the mockup — manifest-driven, so a new plugin
  needs zero frontend changes to render correctly.
- `components/GridToolbar.tsx` — the grid visibility/spacing/opacity/style
  popover from the mockup, now driving React Flow's *native* `Background`
  and `snapToGrid`/`snapGrid` props rather than a hand-rolled CSS grid —
  correct under pan/zoom, which the standalone mockup couldn't fully prove.
- `components/Inspector.tsx` — selected node's manifest, ports, params,
  URDF binding, and a live value panel driven by `/ws/bus`, filtered to
  that node's own output topic.
- `hooks/useGraph.ts` — the single source of truth: loads plugins + graph
  state from the backend, wraps every mutation (add/remove node, connect,
  start/stop) in the matching API call, and keeps React Flow's node/edge
  state in sync. Canvas *position* is frontend-only (persisted to
  `localStorage`) since the backend intentionally only tracks topology.
- `hooks/useBusSocket.ts` — a reconnecting WebSocket client for `/ws/bus`,
  keeping both "latest message overall" (topbar timecode) and "latest
  per topic" (Inspector live value) up to date.
- ✅ Verified: `npm run build` (`tsc -b && vite build`) completes clean
  with no type errors; the backend's CORS preflight was confirmed to
  actually return the headers the dev-server origin needs
  (`access-control-allow-origin: *`) so the two can talk cross-port.

### 7. Live Params (`sdk/pyrobot_plugin/node.py`, `backend/app/graph.py`) — NEW in Phase 4
- `Node.update_params()` + `on_params_changed()` hook — a node can react
  to a live param change (e.g. restart its capture loop at a new rate)
  instead of only picking up new values on next start.
- `PATCH /api/graph/nodes/{id}/params` — validates keys against the
  plugin's manifest before applying (unknown key -> 400, not silently
  ignored).
  - ✅ Verified with a real behavior change, not just a dict update:
    patched a running Fake IMU node from 20Hz to 200Hz mid-flight and
    measured the actual message rate jump (~10 -> ~96 messages in 0.5s)
    over the live WebSocket (`tests/test_backend.py`).

### 8. Rerun 3D/SLAM Viewport (`core/viz/rerun_bridge.py`) — NEW in Phase 4
- Backend starts a real Rerun gRPC log stream + web viewer at startup;
  any plugin logs to it with a plain `rerun.log(...)` call, no
  plugin-specific wiring needed. `GET /api/viz/url` exposes the viewer
  URL to the frontend.
- `plugins/examples/pointcloud_viz.py` — a synthetic SLAM stand-in
  (drifting point cloud + an actually-accumulating trajectory trail —
  logging a single replaced point per frame would NOT show a trail in
  Rerun's live view, so the plugin maintains and re-logs the growing
  point list each frame) until a real SLAM algorithm is wired in.
- `frontend/src/components/RerunViewport.tsx` — embeds the web viewer in
  an iframe, toggled from the canvas toolbar. Deliberately not
  reimplemented in React — Rerun's own viewer already handles camera
  controls and timeline scrubbing correctly.
  - ✅ Verified: while a node is actively logging, the Rerun web viewer
    responds HTTP 200 (`tests/test_rerun_integration.py`) — not just
    "the process didn't crash."

### 9. Real Device & Processing Plugins (`plugins/devices/`, `plugins/processing/`) — NEW in Phase 4
- `camera_source.py` — real OpenCV capture; falls back to a synthetic,
  genuinely-animating test pattern when no camera hardware is present so
  the graph stays runnable during development.
  - 🐛 **Caught and fixed a real bug here**: the synthetic frame generator
    overflowed doing `uint8 % 256` and silently crashed the capture
    thread. Fixed by widening to `int16` before the modulo.
- `can_reader.py` / `can_writer.py` — real `python-can` I/O against any
  interface (`socketcan`, `virtual`, `pcan`, ...).
  - ✅ Verified against a **virtual CAN bus with an externally-injected
    frame** — a completely independent `python-can` connection sends a
    frame, and the plugin picks it up for real (`tests/test_device_plugins.py`).
- `serial_reader.py` — real `pyserial` line reading.
  - ✅ Verified against a **real OS pseudo-terminal pair** (`pty.openpty()`)
    standing in for a USB-serial device — indistinguishable to the plugin
    from real hardware.
- `pointcloud_filter.py` — real voxel-grid downsampling (not a stub).
  - ✅ Verified with exact centroid math against known input/output, plus
    edge cases (empty cloud, no-merge case) (`tests/test_pointcloud_filter.py`).
- 🐛 **Caught a second real bug** while testing CAN: injecting the test
  frame *before* opening the WebSocket subscriber raced ZeroMQ's
  "slow joiner" behavior (a subscriber connecting after a publish misses
  it) and silently ate the one-shot message. Continuous-stream plugins
  (IMU, camera) never hit this by luck; fixed by subscribing first.

### 10. Plugin CLI (`sdk/cli.py`) — NEW in Phase 4
- `python -m sdk.cli create-plugin <name> --category ... --input name:type --output name:type`
  scaffolds a ready-to-run source or processing node — correct manifest,
  correct base-class hooks, TODOs only where real logic has to go.
  - ✅ Verified the generated code isn't just syntactically valid: ran the
    CLI as a real subprocess, discovered the output with the actual
    `PluginRegistry`, instantiated both generated classes, and confirmed
    messages flow from the generated source node to the generated
    processing node over the bus (`tests/test_cli_scaffolding.py`).
- `plugins/user/` is the landing spot — auto-discovered, documented with
  its own README.

**Running it:**
```bash
# terminal 1 — backend
cd pyrobot-studio
pip install -r requirements.txt
uvicorn backend.app.main:app --port 8000

# terminal 2 — frontend
cd pyrobot-studio/frontend
npm install
npm run dev
# open the printed localhost URL (default http://localhost:5173)
```
`node_modules/` isn't included in the archive (137MB) — `npm install`
pulls it fresh from your `frontend/package.json`.

## Not built yet
1. Porting the rest of the 26+ V3 nodes not covered above (ZED SDK,
   RealSense — camera_source.py covers generic webcams, not those SDKs
   specifically)
2. DevBus as a distinct aggregator concept (each device plugin publishes
   independently today; a dedicated "DevBus Publisher" that fans multiple
   device topics into one namespace hasn't been built)
3. Hot-reload dev server for plugins (CLI scaffolding exists; live
   reload without restarting the backend does not)
4. A real SLAM algorithm (fast-lio, etc.) — `pointcloud_viz.py` is a
   synthetic stand-in proving the Rerun pipeline works, not a working
   SLAM implementation

## Running the full test suite
```bash
pip install -r requirements.txt

for f in tests/test_*.py; do python3 "$f"; done
```
Each file is also runnable standalone and prints its own pass/fail per
check. `test_backend.py`, `test_rerun_integration.py`, and
`test_device_plugins.py` each start their own FastAPI TestClient (which
spins up a bus broker); running two in the *same* Python process can hit
a harmless `Address already in use` on the second one — running the files
as separate processes (as above) avoids it.
