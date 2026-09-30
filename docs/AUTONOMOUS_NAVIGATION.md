# Autonomous navigation: staged implementation

## Step 1: navigation execution and recovery

The A* navigation plugin now provides bounded recovery for the supported planar
four-wheel pipeline. Existing saved projects receive the new parameter defaults.

| Condition | Behavior |
| --- | --- |
| No accepted mapping update for 1.5 seconds | Publish zero velocity and `sensor_timeout`; discard the old path |
| Duplicate or out-of-order observation time | Ignore it; it does not refresh the sensor watchdog |
| Fresh data after a timeout | Replan before moving; an existing navigation failure remains latched |
| No route or close front obstacle | Stop linear and angular motion; replan at most once per second of observation time |
| Continuously blocked for `blocked_timeout` (default 8 seconds) | Publish zero velocity and `navigation_failed` |
| Less than 8 cm translation within `progress_timeout` (default 12 seconds) | Publish zero velocity and `stalled` |
| New goal/waypoints or explicit retry | Clear old commands immediately; wait for a fresh observation before moving |
| Paused or goal completed | Stop; reset the progress budget |

Failure budgets use monotonic wall time, not simulation time. The progress check
allows turns within its timeout but does not regard spinning in place as route
progress. Small pose noise below 8 cm does not reset the budget. Short alternating
blocked/clear intervals still count toward the no-progress timeout.

On `stalled` or `navigation_failed`, clearing the map obstruction alone does not
restart motion. Check the robot and route, then use **Retry navigation**, submit
a new goal/waypoint mission, or explicitly resume navigation. The UI explains the
failure. `NavigationPath@1` additionally reports optional `reason` and `replans`
fields and the new statuses; update Studio and runtime together.

This recovery does not command blind reversing or obstacle-avoidance maneuvers.
It is a software stop request, not proof that physical actuators stopped. Sensor
freshness checks observe accepted mapping updates, not calibrated end-to-end
sensor latency. The current SLAM interface has no localization confidence signal;
detecting localization loss, pose jumps and relocalization needs further work.

## Verification

`python tests/test_navigation_recovery.py` checks bounded no-route retries,
latched failures, explicit retry, stationary and moving poses, duplicate-data
expiry, timeout recovery, goal-change heartbeat cancellation, pause/resume and
full obstacle stops. These tests control time directly and require no hardware.
Run the full Python suite and frontend build for integration regressions.

## Step 2: return to home

Start the graph and wait for mapping. The first accepted map pose is captured as
this run's home unless `home_pose` is explicitly configured. In the simulation
panel, **Set home here** pauses navigation and stores the current map pose
`[x, y, yaw]` in the navigator parameters. **Save project** retains this explicit
home; the automatic first-pose capture is session-only and is recaptured on a
new run. An empty `home_pose` restores that automatic behavior.

**Return home** selects autonomous control and replaces the active route with a
route to home. The previous waypoint list is retained but is not automatically
resumed. **Navigate** or **Run waypoints** exits return-home mode and starts the
selected mission. Pause/Stop uses the same controls as normal navigation; Resume
continues the home mission if it is still selected.

Arrival requires being within 0.25 m of home and within 0.1 rad of its saved
heading. The robot turns in place to align, then reports `home_reached` and stays
stopped even if subsequent pose estimates drift. Press Return home again to
explicitly retry that mission. This is arrival at a pose, not docking or charging.

Home routes use the same obstacle inflation, no-path timeout, progress watchdog
and stale-data stop as outbound navigation. An unreachable home reports
`navigation_failed` with `returning_home=true`; it does not drive directly through
obstacles or fall back to the interrupted mission. Arrival is based on SLAM pose,
not ground truth. Only reuse a saved home with the same map coordinate system;
map persistence, global relocalization and long-distance return guarantees are
not implemented. Turn clearance and physical stopping need hardware validation.

Verification: `python tests/test_return_home.py` covers capture, persistence,
interruption, cancellation, heading wrap, arrival latching and unreachable home.
`python tests/browser_simulation.py` exercises Set home here and Return home in
the UI. `python tests/webots_smoke.py --project artifacts/car1/car1-webots.project.json --return-home`
adds a home-return leg to the optional car1 Webots test (requires that local draft
and Webots). Run these integration checks separately from the Python suite.

Local verification for steps 1 and 2: all 24 Python test scripts and the frontend
build passed. The browser completed set-home, outbound waypoints and home return.
The car1 Webots test completed its outbound and return legs with zero contacts;
final ground-truth position was approximately (0.046, 0.184) m relative to home
(0, 0), with heading -0.107 rad. These are simulation results, not hardware
qualification.

## Next steps

Validate experimental algorithms over more maps and in Webots; investigate the observed Dijkstra/proportional no-path stop before promoting Dijkstra to a default option.


## Frontier exploration

Start the graph and select **Explore map**. The navigator chooses the nearest reachable free cell bordering unknown space. Exploration paths stay on measured free cells with physical obstacles inflated by the configured clearance. The selection search uses four-connected reachability; route planning allows safe diagonals.

The default limit is 20 selected targets (`exploration_targets`, configurable on the navigation node). Reached or blocked targets are excluded within 0.75 m for the remainder of that exploration run. A blocked route is skipped after the existing blocked timeout; a stalled robot or stale sensors retain the existing stop behavior. Pause/Resume preserves the current exploration session. Explore map starts a new session; Navigate, Run waypoints, Set home here and Return home replace it.

When no eligible reachable frontier remains, or the target limit is reached, the robot returns to the captured/configured home and stops after heading alignment. This means the bounded exploration pass has ended, not that every part of the environment has been mapped. Disconnected areas and excluded frontiers may remain unknown. A failed home route stops with the existing navigation error and requires operator action.

Exploration uses the existing local SLAM pose and is not a guarantee of collision-free autonomous operation. Session targets are reset when the graph restarts; exploration settings persist with the project. Unit coverage is in `tests/test_exploration.py`.

Verification for step 3: all 25 Python test scripts and the frontend build passed. The sensor-driven built-in simulator test selected a frontier, increased mapped cells, returned within 0.4 m of home, and recorded zero collisions. Additional deterministic tests cover pause/resume, target limits, unreachable frontiers and failed-home latching. Browser and Webots exploration runs remain unverified.


## Mission management

Navigation reports now include a session-local `mission_id`, `mission_type`, `mission_state` and `recovery_action`. The UI shows mission type and state independently of the lower-level navigation status.

| State | Behavior / next action |
| --- | --- |
| running | Follow the selected goal, waypoints, exploration pass or home route. |
| paused | Motion is stopped; Resume continues the selected mission. |
| recovering | Replan automatically while blocked, within the configured timeout. Exploration may skip a blocked frontier. |
| waiting_for_sensors | Stop until fresh mapping data arrives. |
| failed | Stop; inspect the cause, then Retry navigation or Cancel mission. |
| completed | Arrival remains stopped; select a new mission to move again. |
| cancelled | Motion remains stopped even on Resume; select a new mission. |

**Cancel mission** immediately discards the cached velocity command and latches cancellation. Navigate, Run waypoints, Explore map or Return home replaces the mission and assigns a new ID. Pause/resume and retry retain the ID. Cancellation is stored in project parameters, so reopening a cancelled project does not silently resume that mission. IDs and execution progress reset when the graph restarts; saved missions are not checkpoints.

Single-goal arrival now latches the stopped command, as waypoint completion and home arrival already did. Existing blocked/stall timeouts, sensor watchdogs and explicit retry remain the recovery policies. A failed return-home route never automatically resumes an outbound task. This implementation manages one active mission; queued missions, persistent execution history and resuming across graph restarts remain future work.

`tests/test_mission_management.py` covers cancellation, resume, replacement, completion drift, sensor waiting, failure and retry. The browser simulation check also exercises Cancel mission followed by Navigate.

Step 4 verification: all 26 Python test scripts, the frontend production build, and the browser simulation workflow passed. Browser coverage includes cancellation followed by a replacement navigation mission. The home-save check now waits for the PATCH response before reading saved parameters. Mission-management changes have not been separately exercised in Webots or on hardware.


## Selectable planners and controllers

Use the simulation panel's **Planner** and **Controller** selectors, or the navigation node's `planner` / `controller` parameters. Existing projects default to A* and proportional control. Settings are stored with project parameters and apply to goals, waypoints, exploration and return-home travel. Home heading alignment retains its existing controller.

- `astar`: heuristic grid search with inflated obstacles and higher cost for unknown cells.
- `dijkstra`: the same graph, costs and clearance rules, searched without a heuristic. It may search more cells; it is not inherently safer than A*.
- `proportional`: existing heading-error path follower.
- `fuzzy`: zero-order Sugeno controller. Five overlapping triangular signed-heading sets blend turn-rate singletons (-1.3, -0.84, 0, 0.84, 1.3 rad/s) and speed fractions (0, 0.35, 1, 0.35, 0). Near/clear frontal-distance memberships scale forward speed between zero at the stop distance and full speed 0.8 m beyond it. Beyond ?0.65 rad heading error, it turns in place.

Both controllers retain the lidar hard stop and navigation watchdogs. Changing algorithms clears the cached command and waits for a fresh observation to replan; it preserves the mission ID, progress and any latched failure. It is not a retry command.

Run `python tests/test_navigation_algorithms.py` for path-cost/corner-clearance checks, fuzzy symmetry and stop rules, live switching, and sensor-driven comparisons. Results are written to `artifacts/navigation-algorithms.json`, including travel distance, elapsed simulated time, goal error and collisions. These bounded scenarios do not establish a generally superior algorithm or hardware safety.


Local comparison (two sensor-driven scenarios, eight runs): all four combinations reached the nearby (0.8, 1.0) m goal. On the (8, 6) m obstacle route, A* + proportional reached in 24.1 simulated seconds, A* + fuzzy in 26.2 s, and Dijkstra + fuzzy in 25.9 s. Dijkstra + proportional stopped with `no_path` after 13.0 s; the benchmark ends after three seconds of continuous blocked status rather than treating that as arrival. All eight runs recorded zero collisions. Dijkstra and fuzzy control are experimental options, and A* + proportional remains the default. The comparison uses mapping/odometry and the planner/controller functions directly; mission watchdogs are covered separately.

Step 5 verification: all 27 Python test scripts and the frontend build passed. Project export/import retains Dijkstra/fuzzy settings. The new selectors have not yet been exercised by the browser test, and the alternative algorithms have not been validated in Webots or on hardware.


## Browser and Webots algorithm validation

`tests/browser_simulation.py` now selects Dijkstra/fuzzy through Studio, verifies the reported selection, and runs waypoints plus return home. Its default algorithm scenario restarts the simulator after the keyboard test to establish a repeatable initial pose. Use `--continue-after-manual` to retain the mixed manual/autonomous stress scenario: a local run failed safely with `navigation_failed` near pose (1.518, 0.582) m after repeated no-path results. This was observed before the command-handoff fix documented below. The test now reports the failure state immediately and waits for UI rendering before checking the home-arrival text.

The Webots smoke test accepts `--planner astar|dijkstra` and `--controller proportional|fuzzy`, in addition to `--project`, `--mesh` and `--return-home`. Successful runs write `artifacts/webots-<planner>-<controller>.json` (the next run of that combination overwrites it).

Verified locally on 2026-09-29, including manual driving, two waypoints, home heading alignment and simulator process cleanup:

| Robot | Planner / controller | Final home distance | Heading error | Contacts |
| --- | --- | --- | --- | --- |
| car1 CAD model | Dijkstra / fuzzy | 0.113 m | -0.089 rad | 0 |
| Reference robot | A* / fuzzy | 0.124 m | -0.077 rad | 0 |
| Reference robot | Dijkstra / proportional | 0.136 m | -0.070 rad | 0 |

Reproduce the custom-model test with:

```powershell
.\.venv\Scripts\python.exe tests/webots_smoke.py --project artifacts/car1/car1-webots.project.json --planner dijkstra --controller fuzzy --return-home
```

These are bounded simulation checks. They do not resolve the longer-route Dijkstra/proportional limitation or qualify arbitrary start poses, exploration, or hardware operation.

The default browser scenario passed after separating the keyboard and algorithm starting states: selector changes, Dijkstra/fuzzy waypoints and home return, pause/resume, mission cancellation/replacement, configuration editing and the expected preflight rejection all completed. No application algorithm changes were made during this validation step; changes were limited to test controls, diagnostics, synchronization and documentation.


## Recovery from grid rounding at the robot pose

A reproduced Dijkstra failure had 0.697 m of clearance at the estimated robot pose but only 0.646 m at its cell centre, against a 0.65 m inflation radius. Planning previously rejected that start outright.

The planner now permits a connection from the actual pose to an adjacent valid cell only if the start is measured free, the actual pose meets the configured clearance, and the entire connecting segment also meets it. Clearance is evaluated against the same occupied-cell centres used by the grid inflation model. This does not shrink the radius, clear occupied cells, move the goal, or permit a genuinely obstructed start. Existing corner-cutting restrictions and failure timeouts remain in place.

All eight built-in algorithm comparisons now reach their goals with zero collisions, including the previously failing Dijkstra/proportional long route (24.4 simulated seconds, 0.198 m final goal error). The comparison test now requires arrival for all eight combinations.

No-path reports distinguish robot/goal clearance violations, occupied cells, out-of-map coordinates and disconnected routes. A robot inside the clearance boundary remains stopped and asks the operator to move into clear space before retrying. This is deliberate; automatic movement out of an obstructed footprint is not implemented.

The mixed manual/autonomous browser case passed twice consecutively after the change; the latest recorded zero blocked motion attempts. An earlier post-change run still failed at a genuinely obstructed pose and recorded simulator blocked attempts, that run motivated the command-handoff fix below. `artifacts/browser-navigation-history.json` now records recent poses, paths and selected commands; failures also save the latest map/sensor messages in `artifacts/browser-navigation-failure.json` for investigation. These files are overwritten by later runs.

Recovery-change verification: all 27 regression scripts and the frontend production build passed. The mixed-mode browser scenario passed twice, as qualified above. Webots was not rerun after this planner change.


## Mixed-mode command handoff fix

Navigation and command-selector parameter updates now acquire their control lock before mutating parameters. Previously the mutation happened before `on_params_changed` acquired that lock, allowing a worker to see new parameters with old cached control state.

The selector also records the session-clock publication boundary of each mode change. A queued command published before that boundary cannot become eligible merely by arriving afterward. Command expiry includes time spent queued, and an older/replayed publication cannot replace a newer command (including a stop). Publication timestamps are compared in the session clock; simulation capture time is not compared against wall time. The existing 0.4 s selector timeout is unchanged.

Focused regression tests deliberately deliver a pre-transition command after a switch, deliver an older movement command after a newer stop, deliver an expired command, and hold each control lock while another thread attempts a parameter update. They verify zero output for rejected commands and atomic updates.

The browser test now keeps the simulation running after manual driving by default and asserts zero simulator collisions through the waypoint mission. `--restart-after-manual` is an opt-in isolated comparison; the older `--continue-after-manual` invocation still runs the mixed-mode default. Recent command history remains available for diagnosing other failures.

Handoff-fix verification: all 27 regression scripts passed, including the new deterministic ordering and concurrency tests. The default mixed-mode browser scenario passed twice consecutively with zero simulator collisions through the waypoint mission. Car1 Webots also passed manual driving, both waypoints and home return using Dijkstra/fuzzy, with zero contacts and final home error approximately 0.158 m / -0.092 rad. These checks validate the repaired transition conditions; they are not a guarantee for every map or hardware setup.


## Map persistence milestone

Map capture and project round trips are now supported through the Maps tab; see [Saved maps](MAP_PERSISTENCE.md). Earlier statements that map persistence is unavailable describe the pre-snapshot implementation. Saved occupancy requires explicit operator starting-pose confirmation for every run. Automatic relocalization and localization confidence remain future work.

## Performance and exploration recovery

See [Simulation performance](SIMULATION_PERFORMANCE.md) for frame pacing, live-view
coalescing, Rerun follow behavior, frontier invalidation and rotation-aware progress
checks, along with the commands and limits of the performance measurements.
