<!--
SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
SPDX-License-Identifier: Apache-2.0
-->

# Simulation performance and exploration recovery

The built-in simulator now schedules frames against a monotonic deadline, so
sensor and camera processing are included in the frame budget. Overloaded frames
do not trigger a burst of catch-up steps.

Studio uses `/ws/bus?preview=true` to coalesce live previews to the latest value
per topic at up to 10 Hz. The ordinary bus WebSocket retains its existing stream
behavior. Neither setting throttles the internal control bus.

The simulation Rerun sink sends JPEGs directly, logs fixed robot transforms once
per run, limits map/lidar/status updates, and records trail points only after
movement. Its default timeline follows `log_time`, which continues across graph
restarts; `simulation_time` remains available for inspection.

Exploration immediately rejects targets that new map observations place inside
obstacles or their clearance boundary. Known-space routes now share the planner's
safe connection from a continuous start pose to an adjacent grid cell. A blocked
or unobserved start is reported as a failure rather than exploration completion.
The progress watchdog accepts measured rotation while a turn is commanded, but
still stops a robot whose pose stays frozen.

The follower checks its lookahead segment against occupied-cell clearance before
cutting across a path bend. It also checks the commanded arc over a 0.4-second
horizon and reduces forward speed when that arc would enter mapped clearance.
This uses the configured inflation radius, not a smaller footprint. The existing
lidar stop remains active. It cannot predict obstacles that have not been observed.

## Reproduce the measurements

From the repository root:

```powershell
.\.venv\Scripts\python.exe tests/performance_simulation.py --explore --seconds 15 --output artifacts/performance.json
.\.venv\Scripts\python.exe tests/browser_simulation.py
```

The performance probe runs the reference robot without a browser. It records node
processing time, capture-to-output latency, simulation progress, navigation status
and collision count. `--targets 20 --seconds 60` runs a longer exploration probe.
Capture latency is diagnostic wall-clock time, not a control deadline or a browser
render-latency measurement.

The initial 15-second local comparison advanced 13.8 simulated seconds before the
changes and 15.0 after. Mean viewer processing decreased from 2.49 to 1.69 ms per
received input; mean sensor-capture-to-selected-command age decreased from 141 to
130 ms. These are single-run observations, not performance guarantees. The raw
reports are `artifacts/performance-before.json` and `artifacts/performance-after.json`.

A subsequent 60-second, 20-target probe reproduced a clearance failure after seven
targets. After the corner-tracking checks, a repeat advanced 60.1 simulated seconds,
selected 11 targets and was returning home at the end, with zero collisions.
Mean selected-command age was 136 ms (95th percentile 189 ms); mean navigation
processing was 4.55 ms. This run ended before home arrival. Its report is
`artifacts/performance-long-exploration-fixed.json`.

Exploration is still bounded by the configured frontier-attempt limit and returns
home when that limit is reached or no eligible reachable frontiers remain. It does
not guarantee complete map coverage. Genuine footprint-clearance violations still
require operator recovery; automatic escape from obstacles is not implemented.

## Final verification

All 28 regression scripts passed, including the extended sensor-driven exploration
test with the default 20-target budget through home arrival and zero collisions.
The frontend production build passed. The final mixed-mode browser scenario passed
manual driving, Dijkstra/fuzzy waypoints, home return, pause/resume, map export/open
and restored-map restart. Browser logs include an expected HTTP 400 from the
negative preflight check.

These checks do not measure end-to-end browser render latency. The automated Edge
test uses software rendering; visual smoothness on the user's GPU remains to be
confirmed. Restart the backend and refresh Studio to load the changes.
