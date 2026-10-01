<!--
SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
SPDX-License-Identifier: Apache-2.0
-->

# Selecting existing Webots worlds

World setup is a separate button beside Robot setup in the top bar. It works with an empty project or an existing supported four-wheel simulation. Stop Graph before changing worlds.

1. Open **World setup**. Select an installed world or enter an external `.wbt` path on the backend computer.
2. Set the robot spawn X/Y, heading in radians and base height. Choose a clear, level floor in the source world. Mapping bounds should cover the area you intend to explore (maximum 512 cells per axis). These bounds do not give the robot an obstacle map.
3. Click **Check world** and review the removed robot nodes and compatibility notices. Check the reset box, then **Apply world**. Changing worlds clears saved maps, home and missions and stops motion.
4. If starting with an empty project, open **Robot setup**, choose your supported robot and apply. The selected world is retained and Webots is the default simulator. Existing supported simulation graphs are converted to Webots while retaining robot URDF/assets and wiring.
5. **Start Graph**. Check the robot position in Webots before selecting autonomous drive and **Explore**. Use **Return home** after exploring. Inspect SLAM and mission status in Studio; the original environment is visible in Webots and the robot camera.

## Try these first

- Repository fixture: `tests/fixtures/external-room.wbt`, spawn `(0,0,0)` and base height `0.002`. An enclosed room with an asymmetric obstacle. Tested with manual motion, two navigation waypoints and return home, with no reported contacts.
- Installed world: `samples/environments/indoor/worlds/apartment.wbt`, spawn X `-4.65`, Y `-4.2`, heading `0`, base height `0.002`, mapping bounds `[-15,-15,15,15]`. Tested loading the apartment, replacing its robot nodes, camera/lidar and nonzero SLAM starting position. Full autonomous exploration of this apartment has not been qualified.

Spawn clearance depends on your robot dimensions. Coordinates above were tested with the sample four-wheel robot. Structural preview cannot guarantee a safe spawn. Early body contact, tipping or a large height drop produces an actionable simulation error; inspect placement even when no error is reported.

## How unknown-map navigation works

Webots supplies lidar, wheel encoders, a virtual base-aligned gyro and camera data. The gyro provides a turn angle integrated from angular-rate measurements; it does not supply world position or a ground-truth heading. SLAM starts unknown at the explicitly configured spawn pose; it does not receive Webots walls, furniture or ground-truth pose. The existing frontier explorer chooses reachable boundaries of observed free space. Existing A*/Dijkstra planners and proportional/fuzzy controllers operate on the sensor-built occupancy map. Return home depends on that map and pose estimate.

This is local planar SLAM, not robust global localization. The scan matcher now rejects corrections in directions that a wall or corridor cannot reliably measure; a noisy single-wall regression that previously drifted 1.24 m now stays within 3 cm (under 1 mm in the recorded seeded run). Motion in those directions still relies on wheel odometry and can drift with physical slip. Distinctive enclosed geometry passed the waypoint/return-home test. Repeated geometry, wheel slip, narrow passages, slopes, stairs, dynamic obstacles and large maps can still cause drift, stalls or incomplete exploration. Goal completion is an estimated pose result, not independent proof of physical arrival.

### Exploration regression status (2026-10-01)

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
- Imported worlds receive Studio wheel contact pairs for `default`, `floor` and explicitly named materials, using friction 0.8 and force-dependent slip 0.02. These affect only the inserted robot's private wheel material; existing environment contact pairs remain. This preserves the approximate skid-steer behavior of Studio's generated room. Hidden contact materials inside remote PROTOs may still need explicit configuration.
- Generated and imported worlds use the same named defaults and contact serializer
  in `core/simulation/wheel_contact.py`. Tune that shared definition rather than
  editing either world generator; a regression checks that both pick up changes.
- Original world files are read-only. Each run generates an isolated world under `artifacts/webots/<run-id>/`. Relative assets are resolved against the original world. Keep the original local world and assets available; official remote assets need Webots cache/network access.
- Project JSON stores the world path, source hash, spawn and mapping settings. It does not bundle the world or its dependencies. Source world changes require checking/applying again. Dependency file contents are not hash-locked.
- Saved occupancy snapshots include the source world hash to prevent reuse with another world.

## Reproduce checks

```powershell
.\.venv\Scripts\python.exe tests/test_world_catalog.py
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
