<!--
SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
SPDX-License-Identifier: Apache-2.0
-->

> Historical guide: retained for reference. Use [README](README.md) for current installation, supported versions and capabilities, and [Baseline verification](docs/BASELINE.md) for acceptance checks. The prerequisites and phase descriptions below describe an earlier revision.

# PyRobot Studio — User Guide

This guide walks through installing, running, and actually using PyRobot Studio: the backend, the Studio UI, the 3D/SLAM viewport, and building your own plugins.

---

## 1. Prerequisites

| Requirement | Why |
|---|---|
| Python 3.10+ | Backend, core bus, plugins |
| Node.js 18+ (with npm) | Studio frontend |
| ~500MB free disk | Python packages (OpenCV, Rerun, etc.) + `node_modules` |

No GPU, no ROS, no external services required. Everything runs locally.

---

## 2. Install

Extract the archive, then set up each half:

```bash
# from the extracted pyrobot-studio/ folder

# --- backend ---
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# --- frontend ---
cd frontend
npm install
cd ..
```

**Tip:** if you have the `setup_and_test.py` script from earlier, running it does all of the above automatically and reports pass/fail on every component before you touch the UI.

---

## 3. Run it

Two terminals, both from the `pyrobot-studio/` root:

**Terminal 1 — backend**
```bash
uvicorn backend.app.main:app --reload --port 8000
```
Leave this running. It starts:
- the message bus broker
- the plugin registry (scans `plugins/`)
- the Rerun 3D visualization bridge
- the REST + WebSocket API on `http://localhost:8000`

**Terminal 2 — frontend**
```bash
cd frontend
npm run dev
```
Open the URL it prints — typically **http://localhost:5173**.

You should see the Studio UI: a node palette on the left, an empty canvas in the middle, an inspector on the right, and a timecode readout top-right that should show a green dot once connected.

---

## 4. Using the Studio UI

### 4.1 Load a robot (optional, only needed for URDF-bound plugins)
Click the **Robot: no URDF loaded** button in the top bar and select a `.urdf` or `.xacro` file. A sample robot is included at `tests/fixtures/sample_robot.urdf` if you just want to try it. Once loaded, any plugin that needs a physical mount point (like a camera or LiDAR) can bind to a real link from that robot.

### 4.2 Add nodes
Click any item in the left **Node Palette** to add it to the canvas. Nodes appear automatically laid out; drag them wherever you like.

Available out of the box:
| Node | What it does |
|---|---|
| Fake IMU Source | Synthetic IMU data for testing |
| Logger | Counts/logs whatever it receives |
| Camera Source | Real webcam capture (falls back to a synthetic test pattern if no camera is found) |
| CAN Bus Reader / Writer | Real CAN I/O via `python-can` |
| Serial Device Reader | Real serial port reading via `pyserial` |
| Point Cloud Filter | Voxel-grid downsampling |
| SLAM (Rerun) | Synthetic SLAM stand-in that drives the 3D viewport |

### 4.3 Connect nodes
Drag from a node's **output jack** (right edge, small circle) to another node's **input jack** (left edge). This calls the backend immediately — it's a real connection, not just a visual line.

### 4.4 Edit parameters
Click a node to select it. Its parameters appear in the right **Inspector**, and are live-editable:
- Number fields: type a value, click away to apply
- Dropdowns: pick a value, applies immediately
- Checkboxes: toggle, applies immediately

Changes apply to the **running** node immediately — no restart needed (e.g. changing a camera's frame rate takes effect on the next frame).

### 4.5 Start / stop the graph
The **Start Graph** button (top right) starts every node in the canvas. Connected wires animate while data is flowing. **Stop Graph** halts everything cleanly.

### 4.6 Canvas grid
The toolbar (top-left of the canvas) has:
- A grid on/off toggle
- A settings icon (gear) opening spacing, opacity, style (dots/lines/cross), and snap-to-grid controls

### 4.7 Side panels
Both the palette and inspector can be collapsed via the arrow button in their header — useful when you want more canvas space.

### 4.8 3D / SLAM viewport
Click the cube icon in the canvas toolbar to open the bottom 3D panel. Add a **SLAM (Rerun)** node and start the graph — you'll see a live point cloud and a moving trajectory trail. This is a real, interactive 3D view (orbit/pan/zoom with your mouse) rendered by [Rerun](https://rerun.io), not a static image.

### 4.9 Inspecting live data
With a node selected, scroll down in the Inspector to **LIVE VALUE** — it shows the actual JSON payload most recently published by that node, updating in real time.

---

## 5. Building your own plugin

Every plugin is a single Python file. Use the CLI to scaffold one:

```bash
# a source node (generates data on its own — sensors, timers, etc.)
python -m sdk.cli create-plugin my_sensor --category Sensors --output reading:number

# a processing node (reacts to input, optionally emits output)
python -m sdk.cli create-plugin my_filter --category Processing \
    --input in:number --output out:number
```

This creates a ready-to-run file in `plugins/user/` with a correct manifest and stubbed lifecycle methods — fill in the `TODO`s with your real logic, then restart the backend. It will appear in the Studio palette automatically; no registration step.

**Port types available:** `image`, `pointcloud`, `pose`, `imu`, `string`, `number`, `bool`, `json`, `any`

**Reference plugins to read** (in order of complexity): `plugins/examples/fake_imu.py` → `plugins/processing/pointcloud_filter.py` → `plugins/devices/camera_source.py` → `plugins/devices/can_reader.py`

---

## 6. Exploring the API directly

With the backend running, open **http://localhost:8000/docs** — an interactive Swagger UI where you can call every endpoint (upload a URDF, add nodes, connect ports, start/stop) directly from the browser. Useful for scripting or debugging without the frontend.

---

## 7. Verifying your install (automated)

```bash
for f in tests/test_*.py; do python3 "$f"; done
```
Each file prints its own pass/fail. Expect 8 files, all passing, covering the bus, timing system, URDF parsing, the backend API, live param updates, Rerun integration, the device plugins (camera/CAN/serial), and the plugin CLI.

---

## 8. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Frontend shows "bus·offline" in the topbar | Backend isn't running, or is on a different port than `frontend/.env`'s `VITE_BACKEND_URL` (default `http://localhost:8000`) |
| Adding a node fails with "requires a URDF link" | Load a robot URDF first (§4.1) — some plugins need a physical mount point |
| Camera Source shows `"source": "synthetic"` | No camera hardware detected at that device index — this is expected fallback behavior, not an error |
| CAN/Serial node logs an error and idles | The configured channel/port doesn't exist on your machine — expected without real hardware attached; the rest of the graph keeps running |
| `Address already in use` on the bus ports (5555/5556) | Another backend instance is already running — stop it first, only one broker per machine at a time |
| 3D viewport button is greyed out | Rerun bridge failed to start — check the backend terminal for a startup error |

---

## 9. What's not built yet

Worth knowing before you rely on this for a real deployment:
- ZED SDK / RealSense-specific camera integration (Camera Source covers generic webcams only)
- A dedicated DevBus aggregator (each device plugin currently publishes independently)
- Plugin hot-reload (changes require a backend restart)
- A real SLAM algorithm (the SLAM node is a synthetic stand-in proving the 3D pipeline works)
