# Runtime contracts and reference-robot configuration

This update addresses message compatibility, missing connections, startup loss,
timestamp propagation, failure containment and fixed reference-robot settings.
Restart the backend and frontend to use the updated plugins and controls.

## Message contracts

Ports may declare an exact versioned schema:

```python
PortSpec("command", PortDataType.JSON, schema="pyrobot/VelocityCommand@1")
```

A typed input requires the same schema ID on the output. Arbitrary JSON cannot
connect to a typed input. Untyped legacy ports and generic sinks such as Logger
remain supported. Thus legacy-to-legacy JSON connections remain unchecked until
those plugins adopt schemas; this is an explicit compatibility boundary.

`core/messages.py` defines LaserScan, Odometry, Image, JointState,
VelocityCommand and OccupancyGrid, plus SensorPacket, Observation, MappingState
and NavigationPath for the reference pipeline. The latter composite messages
keep synchronized lidar/encoder observations together. Odometry and velocity
contracts currently describe planar motion; they are not general 6-DoF messages.

Publication and receipt validate structure, schema version, finite values,
coordinate frames, unit literals and relevant array dimensions. Outputs
materialize declared defaults, including schema_version=1. Units are metres,
radians, seconds and encoder ticks as appropriate. Frame names describe the
coordinates; declaring a frame does not automatically transform measurements.
Camera payloads use JPEG/base64; binary transport is still future work.

## Startup and failure policy

`GET /api/graph/preflight` reports node/port diagnostics without opening hardware.
Starting checks every required input, known schemas and node configuration.
There is one source per input; multiple sources need an explicit merge or command
arbitration node. Optional inputs use `required=False`.

During startup, nodes stage publications in bounded buffers (1024 per node).
The runtime repeatedly exchanges internal readiness probes through each input
and output route. Only after routes and nodes are ready does it release the
staged messages. A timeout or failed node rolls startup back. This protects
one-shot initialization within the running graph, including cyclic graphs;
it does not add general reliable delivery to ZeroMQ or replay to late subscribers.

Every graph start creates a new run_id. Nodes and bridges discard messages from
older executions, preventing previous simulated timestamps from contaminating
a restarted estimator. External publishers targeting graph inputs must use the
active run_id, available from `GET /api/graph`, and the declared schema.

The current failure policy is deliberately **stop the entire graph**. Invalid
payloads, callback failures, reported worker failures and unexpected worker exits
are detected. The supervisor checks every 50 ms, closes all publication gates,
signals worker stop events, then performs cleanup. Failed node diagnostics remain
available in the API and Studio. CAN send errors now propagate instead of being
logged as though processing could continue.

Adding or connecting nodes requires a stopped graph. Removing nodes or wires
stops the graph first. Parameters with the SDK's default restart behavior restart
the graph through the same readiness protocol; live-update plugins retain their
explicit handlers. Restarting the simulation resets its map and robot pose.

This is cooperative in-process containment. Python cannot forcibly terminate a
blocked native driver; joins have timeouts and report failure. Physical actuator
drivers still need their own stop/disable implementation and controller watchdog.
Process isolation and independent hardware supervision remain future work.

## Capture and publication time

Bus envelopes now carry:

- `ts`: original capture timestamp and sensor source ID.
- `published_ts`: publication timestamp and publishing node ID, in session time.
- `clock_domain`: `session` or `simulation` for the capture timestamp.
- `schema`: exact payload contract, or null for a legacy port.
- `run_id`: graph execution identifier.

Synchronous callbacks and WorkerNode processing preserve incoming capture time
automatically. Bridges retain both timestamps. For your own background workers,
retain the incoming BusMessage and use `with self.processing(message):` around
processing and emission, or pass an explicit timestamp and clock domain.

Sources should capture before encoding or other expensive work:

```python
captured = self.capture_time()
payload = encode_measurement()
self.emit("out", payload, timestamp=captured)
```

The simulator captures each step once and stamps its sensor, truth and camera
outputs with that simulated instant. Simulation time is independent of wall
speed; a new run_id identifies a reset. Session clocks use a monotonic anchor so
wall-clock adjustments cannot reverse elapsed time. This is a local clock model,
not a claim of synchronized clocks across multiple robot computers.

## Configuring another four-wheel robot

Stop the graph, then choose **Robot configuration** below the canvas. The editor
accepts validated JSON. **Apply configuration** checks it; **Save project** embeds
it in the exported document. Failed changes preserve the previous configuration.
The same data is available through `PATCH /api/project/robot-config`.

Settings are grouped into:

- `drive`: drive type, base frame, two left and two right wheel joint names,
  lidar/camera frame names, optional wheel-radius override, collision radius and
  encoder ticks per turn.
- `environment`: room bounds and obstacle boxes `[xmin, ymin, xmax, ymax, height]`.
  Room walls are generated from the bounds.
- `mapping`: origin, width/height in cells, resolution and obstacle inflation.

Wheel centers and track come from composed URDF mount transforms. Radius comes
from cylinder geometry or the explicit override for mesh wheels. The renderer
uses the configured joint names and cached transform chains, rather than name
suffixes. Floor size, sensor mounts and map dimensions follow the configuration.
Navigation goals are checked against the configured map instead of fixed limits.

The supported drive is `four_wheel_differential`: two wheels on each side, equal
radii, rotating axes aligned with base +Y, fixed wheel mounts and level sensors.
Unsupported drive types, missing joints and incompatible geometry produce
diagnostics. Ackermann, mecanum, legged motion, tilted scanners and full dynamics
require additional models; arbitrary URDF files are not silently approximated.
The simulator starts at (0, 0, 0); configuration rejects a colliding start.

Exports now use project schema_version=2. Version 1 projects remain readable and
receive the original reference configuration defaults. Old applications that
only support version 1 should not open version 2 exports. External meshes and
plugin source still are not bundled.

## Optimization and verification

Occupancy ray sampling uses batches of 64 rays instead of hundreds of separate
linspace allocations. A local fixed-scan benchmark of 100 complete mapping
updates measured 1.501 s before and 0.435 s after, with identical resulting grids.
This is a microbenchmark, not an end-to-end latency guarantee. Rerun caches URDF
origin matrices, and health polling retains unchanged React node/edge objects.

Run `python tests/run_all.py`, plus `npm run build` and `npm run lint` in frontend.
`tests/test_runtime_hardening.py` covers malformed contracts, missing wiring,
one-shot startup, readiness rollback, worker failure, capture propagation,
run isolation, wall-clock changes and renamed robot configuration.
`tests/browser_simulation.py` additionally exercises configuration and startup
diagnostics using isolated servers and Microsoft Edge/Playwright.
