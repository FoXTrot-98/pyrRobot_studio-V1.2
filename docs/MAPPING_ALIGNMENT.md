# Car1 pose and mapping alignment

The 3D mesh shows the physical simulator pose. The yellow box shows SLAM's estimated pose, which the planner uses. They intentionally remain separate: snapping the mesh to the estimate would conceal localization errors. No ground-truth pose or world obstacle list is fed into SLAM/navigation.

## Fixes

- Scan-to-submap ICP now checks which directions the observed geometry constrains. It retains the encoder prediction in unobservable directions instead of amplifying noise along a single wall or corridor. Regularization applies to the total correction, not separately to seven iterative steps.
- Imported Webots worlds receive the same approximate wheel slip/friction settings as Studio's generated room, scoped to a private wheel material. Without them, car1 barely rotated on the apartment floor while its encoders predicted rotation. Existing environment contacts and source files remain unchanged. Material-pair matching follows the [Webots ContactProperties reference](https://cyberbotics.com/doc/reference/contactproperties?version=released).
- The yellow estimate box uses the robot's fixed body dimensions and origin, including rotated offsets. It no longer uses hardcoded sample-robot dimensions.
- Max-range/no-return lidar beams are no longer rendered as measured green obstacle points. Navigation status distinguishes actual model and estimated pose and shows heading as well as position difference. The displayed difference compares latest messages; the diagnostic tests below compare matching simulation timestamps.

## Delayed-scan wall drift fix

A second failure was reproduced by replaying the car1 recording while processing only every third scan. The latest-message worker deliberately drops old scans to avoid a backlog, but the old matcher allowed only seven 0.03-radian correction steps regardless of the encoder change. During skid-steer turns, the accumulated encoder error exceeded that limit and corrupted the map.

The matcher now uses a bounded scan-based heading search when encoder rotation is large, then adapts its iteration budget to that rotation. Exact nearest-neighbor KD-tree queries replace the full pairwise distance matrix, and nearby-reference indexes are cached. No new dependency or simulator truth input is introduced.

Replay results (maximum position error): every third scan improved from 2.23 m to 0.020 m; every sixth from 3.10 m to 0.018 m; every tenth from 3.08 m to 0.028 m. Live car1 testing with an artificial 350 ms mapper delay completed the imported-room four-waypoint circuit with 0.013 m maximum position error and zero contacts. A delayed apartment turn test stayed within 0.015 m. In the imported-room final map, occupied cell centres were at most 0.075 m from the actual wall/obstacle surfaces, consistent with the 0.15 m grid resolution.

To reproduce processing pressure, add `--mapping-delay .35` to the Webots diagnostic command below. The diagnostic now saves the final occupancy state as well as synchronized pose/scan records. The regression suite also checks wall positions after delayed scans and strongly slipping turns.

These are bounded local-mapping tests, not a guarantee of recovery from arbitrary long outages or global localization loss.

## Circular worlds and gyro stabilization

Saved run records identified `projects/humans/pedestrian/worlds/pedestrian.wbt` among the selected worlds. Its circular arena has a 10 m radius, beyond the 9 m lidar range at the centre. Removing its original Robot-based pedestrians leaves no nearby features there. Skid-steer wheel encoders alone cannot measure the chassis heading accurately; circular walls also leave heading ambiguous once they enter range.

Generated Webots robots now include a virtual base-aligned `Gyro`. Its measured Z angular rate is integrated every 20 ms and included as optional `gyro_yaw` in sensor/observation packets. The angle is relative to the run start, not a world heading or Supervisor pose. Encoders still measure travel; gyro measurements stabilize the heading used by odometry and SLAM, while lidar corrects translation. Old packets without this field retain encoder/scan heading estimation.

This is an ideal simulated gyro with no added bias model. A physical robot must supply and calibrate its own gyro; this change does not imply the STEP model contains a real IMU. Integrated gyro bias is not globally corrected, and local SLAM still has no loop closure.

Car1 completed the pedestrian-world four-waypoint circuit with a 350 ms artificial mapping delay, maximum position error 0.034 m, heading error below 0.003 degrees and zero collisions. Of 257 occupied final map cells, 95% were within 0.13 m of the circular wall on the 0.15 m occupancy grid (maximum 0.19 m). This validates wall placement, not only estimated vehicle position.

```powershell
.\.venv\Scripts\python.exe tests/webots_mapping_smoke.py --project artifacts/car1/car1-webots.project.json --world 'C:/Program Files/Webots/projects/humans/pedestrian/worlds/pedestrian.wbt' --turn-seconds 3 --mapping-delay .35
```

## Validation

The seeded single-wall regression previously drifted 1.24 m with exact encoder odometry; the correction reduced it to approximately 0.0008 m. This is a controlled regression, not a general accuracy guarantee.

Car1 completed repeated left/right turns and a four-waypoint circuit in the generated room with maximum matched pose error 0.023 m and heading error 0.018 rad, with zero reported collisions. An apartment turn test stayed within 0.020 m and 0.008 rad after restoring the wheel contact approximation. A four-waypoint circuit in the imported room with a 1.2-radian starting heading stayed within 0.011 m and 0.007 rad, with zero collisions.

```powershell
.\.venv\Scripts\python.exe tests/test_mapping_stability.py
.\.venv\Scripts\python.exe tests/webots_mapping_smoke.py --project artifacts/car1/car1-webots.project.json --turn-seconds 5
.\.venv\Scripts\python.exe tests/webots_mapping_smoke.py --project artifacts/car1/car1-webots.project.json --world tests/fixtures/external-room.wbt --spawn 0 0 1.2 --turn-seconds 3
```

The Webots diagnostic compares sensor/SLAM and actual poses at matching timestamps. It writes `artifacts/webots-mapping-diagnostic.json` and fails on excessive pose drift, mission failure or collision. The local car1 draft must exist to run these commands.

## Retest in Studio

1. Stop Graph and restart Studio's backend so it loads the changed Python code. Start Graph creates a new Webots world/controller automatically.
2. Reopen the car1 project. If it contains an old distorted saved map, open **Maps** and choose **Remove saved map and reset home** while stopped. Existing corrupted maps cannot be repaired by changing the live matcher.
3. Confirm the world and spawn, then start. First drive a short straight segment and a left/right turn. The mesh and yellow estimate should remain close, and static walls should stay in place as the car rotates.
4. Try a short waypoint mission before a long exploration run.

Local SLAM still lacks loop closure/global relocalization. Slippery floors, repeated geometry and unobservable motion can cause drift; external-world exploration clearance recovery remains a separate known limitation. These fixes do not qualify every world or calibrate a real robot's physics.
