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

## Mixed-mode navigation stall follow-up (2026-10-04)

The intermittent browser failure was reproduced: navigation produced a route,
but the true robot pose stayed at the origin and the mission reported `stalled`.
Tracing the drive selector showed commands arriving several seconds after
publication. Its 400 ms freshness check correctly rejected them. This was a
message-delivery backlog, not a reason to extend the navigation progress timeout.

The embedded broker now uses ZeroMQ's native steerable proxy instead of forwarding
each packet through a Python poll/receive/send loop. A separate control socket
terminates it on runtime shutdown; each socket remains owned by its own thread.
The receiving transport drains ready packets in batches bounded by both count
and elapsed time, preserving service for outbound traffic and health checks.

Browser telemetry is now bounded on the producer thread. Previously, each packet
scheduled an event-loop callback before reaching the bounded browser queue; that
handoff could accumulate work and compete with control delivery. Debug clients
retain the newest 128 packets, while preview clients retain the latest value for
up to 256 topics. Sending happens in batches, without a bus-thread event-loop
wakeup for every packet. This is lossy inspection telemetry, not a recording API;
robot control continues through its separate control channel.

In the final traced built-in browser run, 25 once-per-second selector-input samples
while in autonomous mode averaged 53 ms old, with a maximum of 140 ms. The run
completed waypoints, home return, pause/resume, map reload and graph restart.
These are sampled observations, not a worst-case latency guarantee. The command
freshness threshold, sensor watchdog, mode-switch invalidation and navigation
stall deadline remain unchanged.

The browser regression now requires measured robot translation during manual
driving, rather than accepting a nonzero keyboard message as proof of motion.
Broker regressions cover mixed packet ordering, immediate stop and reuse of the
same endpoints. Telemetry tests cover a paused consumer, preview coalescing and
late callbacks after disconnect.

Two consecutive uninstrumented runs of the strengthened browser regression also
passed the complete workflow, including actual manual movement and return home.
The browser's HTTP 400 log is the expected negative preflight check.
All 35 regression scripts passed on Windows, with the documented POSIX
pseudo-terminal serial-test skip (serial loopback is tested separately).

```powershell
.\.venv\Scripts\python.exe tests/run_all.py
.\.venv\Scripts\python.exe tests/browser_simulation.py
```

The browser test requires Edge and Playwright and runs the built-in sample robot.
Those browser checks do not qualify Webots worlds, physical robot timing, obstructed
pose recovery or sustained CPU overload. Restart the backend and refresh Studio
to use the new transport and telemetry paths.

## Webots turn-response follow-up (2026-10-06)

Live car1 testing exposed a separate return-home clearance failure in
`complete_apartment.wbt`. The robot stopped about 0.41 m from home, with no
reported contacts and an estimated position close to the simulator's true
position. The configured 0.65 m clearance was correctly retained. The original
failure is recorded locally in `artifacts/stall-fix-car1-apartment.failure.json`;
two subsequent runs without a controller change passed, confirming that a single
successful repeat was insufficient evidence of a fix.

Return-path tracing exposed a controller assumption: the clearance prediction
used the requested angular velocity as if the drive achieved it immediately.
One command's ideal arc cleared the obstacle by 0.658 m, but continuing straight
at that speed approached within 0.642 m. A slower physical turn could therefore
enter the clearance zone. The controller now checks both the requested arc and
straight-ahead motion over its existing prediction horizon before allowing
forward speed. It slows or rotates in place when safety depends on an immediate
turn. This applies to both controllers without robot-specific calibration,
reduced clearance or a longer failure timeout.

A regression derived from that corner fails with the old controller and passes
with the change, checking missing, partial and full turn response. This remains
an approximate local motion check: it does not model arbitrary slip, braking
distance, moving obstacles or recovery from an already obstructed pose.

Post-change live checks used the local car1 project, default physics and base
height 0.002 m:

| World / starting X, Y, yaw | Check | Physical home error | Contacts |
| --- | --- | --- | --- |
| External-room fixture / `0, 0, 0` | Manual drive, Dijkstra/fuzzy waypoints, return home | 0.185 m | 0 |
| Complete apartment / `0, 0.96, 0` | 12 simulation seconds exploring, then requested return (run 1) | 0.140 m | 0 |
| Complete apartment / `0, 0.96, 0` | Same check (run 2, different exploration route) | 0.178 m | 0 |

All three finished with `home_reached`; absolute home heading errors were below
0.1 rad. Apartment maximum displacements were 4.11 m and 4.60 m. Local reports are
`artifacts/car1-room-turn-response-fixed.json` and
`artifacts/car1-apartment-turn-response-fixed-{1,2}.json`. These are short
exploration checks with an explicit return request, not automatic exploration
completion, full apartment coverage or statistical reliability qualification.

```powershell
.\.venv\Scripts\python.exe tests/webots_smoke.py --project artifacts/car1/car1-webots.project.json --world tests/fixtures/external-room.wbt --spawn 0 0 0 --spawn-height 0.002 --planner dijkstra --controller fuzzy --return-home
.\.venv\Scripts\python.exe tests/webots_smoke.py --project artifacts/car1/car1-webots.project.json --world "C:/Program Files/Webots/projects/samples/environments/indoor/worlds/complete_apartment.wbt" --spawn 0 0.96 0 --spawn-height 0.002 --explore-seconds 12
```

These commands require the local car1 draft and installed Webots assets; neither
is supplied by a clean checkout. The deterministic corner regression is tracked
in `tests/test_navigation_algorithms.py` and needs neither asset.
All 35 regression scripts passed again after this controller change, including
the new turn-response case; the Windows POSIX serial-test skip remains unchanged.
The complete uninstrumented Studio browser regression also passed after the
controller change: manual movement, Dijkstra/fuzzy waypoints, return home,
pause/resume, map reload and graph restart.
