<!--
SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
SPDX-License-Identifier: Apache-2.0
-->

# Selecting existing Webots worlds

World setup is a separate button beside Robot setup in the top bar. It works with an empty project or an existing supported four-wheel simulation. Stop Graph before changing worlds.

1. Open **World setup**. Select an installed world or enter an external `.wbt` path on the backend computer.
2. Set the robot spawn X/Y, heading in radians and base height. Choose a clear, level floor in the source world. Mapping bounds should cover the area you intend to explore (maximum 512 cells per axis). These bounds do not give the robot an obstacle map.
3. Click **Check world** and review the removed robot nodes and compatibility notices. With a robot configured, this opens a separate motor-disabled Webots preview. Wait for **Robot placement: valid**. If invalid, inspect the environment in Webots, adjust X/Y/heading/base height in Studio and check again. The invalid preview stays open for inspection. Check the reset box, then **Apply world**. Changing worlds clears saved maps, home and missions and stops motion.
4. If starting with an empty project, open **Robot setup**, choose your supported robot and apply. The selected world is retained and Webots is the default simulator. Existing supported simulation graphs are converted to Webots while retaining robot URDF/assets and wiring.
5. After configuring a robot, reopen **World setup** to check its physical placement. **Start Graph** repeats physical and sensor validation before publishing observations or accepting motion commands. Then select autonomous drive and **Explore**. Use **Return home** after exploring. Inspect SLAM and mission status in Studio; the original environment is visible in Webots and the robot camera.

### Placing visually in Webots

If the initial position is obstructed, click **Find nearby safe position** after
the preview connects. Studio tests up to 25 grid positions around the entered
X/Y, spaced by at least the configured robot diameter and restricted to mapping
bounds. Each probe starts at the entered base height and heading and gets up to
three simulation seconds to settle. Motors stay disabled; only the preview robot
is repositioned. **Cancel position search** stops further probes. Paused Webots
must be resumed for the search to advance.

A found position is a suggestion, not an applied project change. Inspect it,
click **Use Webots position**, then **Check world** and **Apply world**. Applying
the old check after searching is rejected, including through the API. If no
candidate passes, adjust the search centre or floor height and retry. The bounded
search can miss narrow free areas and does not discover arbitrary floor levels,
certify traversability, or prove that the entire world is unsuitable.

Select **PyRobot four wheel** in Webots and move it onto clear floor, or edit its
translation in the scene tree. You may pause the preview while editing; resume
it to allow the physics check to run. Once the robot rests safely, Studio enables
**Use Webots position**. Click it to copy the observed X/Y, heading and base
height, then **Check world** again. Moving in Webots alone does not change the
project's saved starting pose. The button remains disabled for collisions,
missing wheel support, tipping or motion. A different floor height therefore
does not require guessing coordinates or weakening collision checks.

## Try these first

- Repository fixture: `tests/fixtures/external-room.wbt`, spawn `(0,0,0)` and base height `0.002`. An enclosed room with an asymmetric obstacle. Tested with manual motion, two navigation waypoints and return home, with no reported contacts.
- Installed world: `samples/environments/indoor/worlds/apartment.wbt`, spawn X `-4.65`, Y `-4.2`, heading `0`, base height `0.002`, mapping bounds `[-15,-15,15,15]`. Tested loading the apartment, replacing its robot nodes, camera/lidar and nonzero SLAM starting position. Full autonomous exploration of this apartment has not been qualified.

Spawn clearance depends on your robot dimensions. Coordinates above were tested with the sample four-wheel robot. The physical check uses the same generated body box and wheel cylinders as simulation: body contact, four-wheel floor support, tilt, displacement during settling and valid sensor samples. It requires at least two simulation seconds and a stable resting interval. Normal startup allows up to eight simulation seconds for these checks to pass, keeping motors disabled and withholding navigation observations throughout. Preview remains editable when invalid. Tolerances are named in `core/simulation/placement_validation.py`. This checks starting placement, not traversability or successful navigation throughout the world.

The actual world and robot are previewed in the native Webots window on the backend computer; Studio provides numeric placement controls and diagnostic status. There is no in-browser clickable floor picker yet. Apply requires a fresh valid result bound to the project revision, world/dependency hash and entered settings. Editing these settings requires another check. Applying, closing World setup or starting the graph closes the preview's own process. A disconnected client expires after 30 seconds without polling. Normal startup always checks placement again.

Robot setup now rejects a clearance radius smaller than the generated body and
wheel footprint. The error reports the minimum radius, rounded upward to a
millimetre. Planning clearance must cover that radius. The sample defaults use
0.55 m robot clearance and 0.65 m planning clearance; imported robots are checked
against their own geometry. The first encoder reading establishes a baseline,
and the gyro heading is expressed relative to the odometry initialization. The
robot should remain stopped until the first sensor observation; motion before
that baseline is not recoverable from a single cumulative encoder reading.

### If Webots opens and then closes

Changing worlds retains the entered spawn; it does not automatically find a
clear floor. In the installed apartment, `(0, 0)` is a floor corner and car1
failed the physical spawn check there. Studio stops the graph and its owned
Webots process on a node failure. This can look like a Webots crash.

Fresh car1 checks loaded the break room and kitchen at `(0, 0, 0)` and the
apartment at `(-4.65, -4.2, 0)`, all with base height `0.002`. All three remained
running with the full Studio/Rerun UI for 30-second checks. These are placement
and sensor checks, not qualification of full autonomous exploration.

After a failure, read Studio's `Graph stopped` message. Placement preview reports
the observed position and reasons for rejection. Every launched run writes
`artifacts/webots/<run-id>/status.json`; controller errors also appear in that
directory's `webots.log`. Reopen World setup, correct the spawn, check/apply the
world, and start again. A non-spawn error in the diagnostic needs investigation;
do not assume every closure is a placement problem.

## How unknown-map navigation works

Webots supplies lidar, wheel encoders, a virtual base-aligned gyro and camera data. The gyro provides a turn angle integrated from angular-rate measurements; it does not supply world position or a ground-truth heading. SLAM starts unknown at the explicitly configured spawn pose; it does not receive Webots walls, furniture or ground-truth pose. The existing frontier explorer chooses reachable boundaries of observed free space. Existing A*/Dijkstra planners and proportional/fuzzy controllers operate on the sensor-built occupancy map. Return home depends on that map and pose estimate.

This is local planar SLAM, not robust global localization. The scan matcher now rejects corrections in directions that a wall or corridor cannot reliably measure; a noisy single-wall regression that previously drifted 1.24 m now stays within 3 cm (under 1 mm in the recorded seeded run). Motion in those directions still relies on wheel odometry and can drift with physical slip. Distinctive enclosed geometry passed the waypoint/return-home test. Repeated geometry, wheel slip, narrow passages, slopes, stairs, dynamic obstacles and large maps can still cause drift, stalls or incomplete exploration. Goal completion is an estimated pose result, not independent proof of physical arrival.

### Exploration regression status (2026-10-01)

The **2026-10-06** car1 follow-up found an intermittent clearance failure on
apartment return. The local controller now checks straight-ahead motion as well
as its ideal turning arc, so clearance does not depend solely on achieving a
commanded turn immediately. Two post-change apartment exploration/return checks
passed with 0.140 m and 0.178 m physical home error and zero contacts; they used
an explicit return request after 12 simulation seconds. See the
[failure evidence, regression and reproduction commands](SIMULATION_PERFORMANCE.md#webots-turn-response-follow-up-2026-10-06).

Follow-up on **2026-10-03**: the local car1 draft passed two runs per world,
exploring for 12 simulation seconds before the test requested return home.

| World / starting X, Y, yaw | Physical home error (two runs) | Maximum distance from home | Contacts |
| --- | --- | --- | --- |
| External-room fixture / `0, 0, 0` | 0.087 m, 0.116 m | 3.18 m | 0 in both |
| Installed complete-apartment / `0, 0.96, 0` | 0.188 m, 0.149 m | 4.53–4.84 m | 0 in both |

Both use base height 0.002 m and the default physics settings. Absolute final
heading error stayed below 0.1 rad. The apartment spawn passed physical startup
validation, but these short paths do not certify full apartment coverage or
recovery from a deliberately obstructed pose. This is two-run evidence, not a
statistical reliability guarantee. Local raw results are in
`artifacts/qualification/20261003T120102.150981Z/summary.json`.

An earlier 12-second exploration run stopped at the obstacle-clearance boundary
with `no_path` and then `navigation_failed` on return home. That historical failure
is retained here, but it did not reproduce in two fresh runs of the original
command with the current mapping/gyro implementation. Both returned home with
zero contacts; the second finished approximately 0.122 m from home.

A separate sample-robot run let exploration select return home itself, without
an operator return command. It travelled up to 1.947 m from spawn and returned
with 0.103 m position error, 0.094 rad heading error and zero contacts. No planner
clearance, failure latch or collision assertion was relaxed for these checks.
This follow-up consolidates contact settings and strengthens regression checks;
it does not introduce a new navigation recovery algorithm or establish which
earlier mapping change resolved the historical run.

The local car1 draft also completed exploration and automatic return in the same
fixture: maximum displacement 3.181 m, final position error 0.123 m, heading error
0.093 rad and zero contacts. Its generated project is a local optional artifact;
the sample-robot commands below are reproducible from the committed fixture.

The smoke test now fails on any observed `navigation_failed`/`stalled` report,
checks physical home position and heading, and writes its latest successful
result to `artifacts/webots-exploration.json`. A navigation failure or timeout
saves map, pose and status diagnostics to `artifacts/webots-exploration-failure.json`.
Automatic escape from a genuinely obstructed pose remains unsupported, and
arbitrary-world exploration is not qualified.

## Supported worlds and portability

- Webots R2025 ENU (Z-up) `.wbt` worlds using native nodes, known installed Webots PROTOs or simple local PROTOs.
- Top-level robot nodes/robot PROTOs are removed; Studio inserts its configured robot. Some interactive devices are Robot-based too and are listed in the preview.
- Nested robots, inline PROTO/IMPORT/EXPORT, physics plugins, custom template PROTOs, unresolved assets and unknown remote PROTOs are rejected with an explanation. The installed catalog is a discovery list, not a claim that every world is compatible.
- Older worlds and other coordinate systems must be converted in Webots first. ROS YAML/PGM, Gazebo worlds and arbitrary mesh terrain import are not part of this feature.
- Imported worlds receive Studio wheel contact pairs for `default`, `floor` and explicitly named materials, using the robot's physics settings (default friction 0.8 and force-dependent slip 0.02). These affect only the inserted robot's private wheel material; existing environment contact pairs remain. This preserves the approximate skid-steer behavior of Studio's generated room. Hidden contact materials inside remote PROTOs may still need explicit configuration.
- Generated and imported worlds use the same named defaults and contact serializer
  in `core/simulation/wheel_contact.py`. Tune each robot through Robot setup;
  a regression checks that both generators use its saved settings.
- Original world files are read-only. Each run generates an isolated world under `artifacts/webots/<run-id>/`. Relative assets are resolved against the original world. Keep the original local world and assets available; official remote assets need Webots cache/network access.
- Project JSON stores the world path, compatibility hash, spawn and mapping settings. The hash includes the world and explicit local URL dependencies, recursively including local PROTOs and directly referenced meshes/textures. Changing those contents requires checking/applying again. Ordinary names and controller arguments are not treated as asset URLs. Remote assets, template-generated paths, custom PROTO parameter indirection and mesh-internal references are not fully content-locked. Files are not bundled; keep untracked dependencies fixed.
- Projects saved with the earlier source-only hash need **Check world → Apply world** once to adopt the new hash. Applying resets saved maps and missions; rebuild the map before exploration.
- Saved occupancy snapshots include the source world hash to prevent reuse with another world.

## Robot physics

Open **Robot setup → Drive → Webots physics** to edit the robot's approximation.
Apply Robot setup and save the project to retain the settings. Check world
placement again after changing them. Existing projects receive the original
defaults when the `robot_config.physics` section is absent.

| Setting | Default | Meaning |
| --- | --- | --- |
| Body mass | 8 kg | Chassis and fixed attachments, excluding the wheels |
| Wheel mass | 0.3 kg | Mass of each of the four wheels |
| Motor torque limit | 8 N m | Per-wheel maximum torque |
| Motor speed limit | 20 rad/s | Per-wheel maximum speed, also enforced by the controller |
| Joint damping | 0.02 N m s/rad | Wheel hinge damping |
| Friction | 0.8 | Wheel contact coefficient |
| Force-dependent slip | 0.02 m/s/N | Approximate wheel slip |

Masses and motor limits must be positive; damping, friction and slip can be zero.
All values must be finite. Generated rooms and imported worlds use the same
saved settings. Imported-world settings affect only Studio's inserted wheels;
other environment contact pairs are preserved. The built-in geometric simulator
does not use these physics settings.

These values are not inferred from STEP/URDF inertial data or calibrated against
hardware. Collision shapes, inertia and center of mass remain approximations.
Changing settings requires validating driving and turning again; a supported
placement alone does not establish reliable navigation or realistic dynamics.

## Reproduce checks

For sequential generated-room and imported-room driving/navigation checks:

```powershell
.\.venv\Scripts\python.exe tests/webots_matrix.py
```

Each run creates a UTC-stamped directory under `artifacts/qualification` with
`summary.json`, per-case logs, and successful-case measurements. Failed cases
remain in the summary and make the runner exit nonzero. Inspect their logs;
missing measurements do not mean zero error. The default cases use the sample
robot, including an imported-world spawn translated and rotated by 90 degrees.

Use `--cases path/to/cases.json` to supply a JSON array of cases. Each case has
`name` and optional `project`, `world`, `spawn` (X/Y/yaw in radians), `planner`
and `controller`. Paths resolve from the repository root. Use checked placements
and ensure the route is clear: the test drives forward manually, visits spawn-relative
waypoints `(0.8, 0)` and `(0.8, 1)`, then returns home. It does not search for a
safe route layout before starting. Project physics settings are retained.

Use `--repeat 2` (or a larger positive count) to repeat every case. For exploration
instead of the manual/waypoint route, add `"explore_seconds": 12` to a case:
the test explores for 12 **simulation seconds**, then requests return home.
Alternatively, `"finish_exploration": true` waits for the navigator to choose
return home itself. `spawn_height` can supply the checked base height. Without
spawn overrides the project pose is retained. Each repeat has a distinct log,
result and, on exploration timeout/navigation failure, a `.failure.json` snapshot.
The summary reports failures and continues with the remaining cases.

Example case for a locally exported car1 project (not bundled with the repo):

```json
[
  {
    "name": "car1-external-exploration",
    "project": "artifacts/car1/car1-webots.project.json",
    "world": "tests/fixtures/external-room.wbt",
    "spawn": [0, 0, 0],
    "explore_seconds": 12
  }
]
```

Save as `artifacts/exploration-cases.json`, then run:

```powershell
.\.venv\Scripts\python.exe tests/webots_matrix.py --cases artifacts/exploration-cases.json --repeat 2
```

Reports include physical waypoint/home errors, home heading error, estimated
versus physical final pose, contact count and the physics configuration. Current
acceptance limits are 0.4 m physical arrival error, 0.2 rad home heading error,
zero reported contacts, and successful navigation status. Final localization
differences use the latest asynchronous messages; they are diagnostic snapshots,
not timestamp-aligned localization benchmarks. Passing these short routes does
not qualify an entire world, exploration, hardware or calibrated dynamics.

```powershell
.\.venv\Scripts\python.exe tests/test_world_catalog.py
.\.venv\Scripts\python.exe tests/test_placement_validation.py
.\.venv\Scripts\python.exe tests/test_placement_search.py
# Reject an incorrect height, retain preview, retry, apply and start sensors.
.\.venv\Scripts\python.exe tests/webots_placement_smoke.py
# Search from car1's failing origin, adopt, recheck, apply and start sensors.
# Requires the local car1 draft and the installed Webots sample world.
.\.venv\Scripts\python.exe tests/webots_placement_smoke.py --project artifacts/car1/car1-webots.project.json --world "C:/Program Files/Webots/projects/samples/environments/indoor/worlds/complete_apartment.wbt" --spawn 0 0 0 --search
.\.venv\Scripts\python.exe tests/webots_smoke.py --world tests/fixtures/external-room.wbt --return-home
# Historical failure scenario: explore for 12 seconds, then request return home.
.\.venv\Scripts\python.exe tests/webots_smoke.py --world tests/fixtures/external-room.wbt --explore-seconds 12
# Explore until the navigator itself chooses to return home (no return command).
.\.venv\Scripts\python.exe tests/webots_smoke.py --world tests/fixtures/external-room.wbt --finish-exploration
$env:PYROBOT_TEST_WORLD = '1'
.\.venv\Scripts\python.exe tests/browser_robot_setup.py
Remove-Item Env:PYROBOT_TEST_WORLD
```

Webots integration and browser tests require an installed Webots and browser. The world unit tests skip when Webots metadata is unavailable.

For delayed-scan and circular-arena drift fixes and car1 test results, see [Mapping alignment](MAPPING_ALIGNMENT.md).

Next work: qualify exploration in multiple installed environments, measure estimated versus true arrival error, improve degenerate-scene localization, and add a visual spawn picker/world asset packaging.
