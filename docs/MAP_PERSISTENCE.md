<!--
SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
SPDX-License-Identifier: Apache-2.0
-->

# Saved maps and the simulation workspace

The simulation panel uses three tabs: **Navigate** for missions, home and exploration; **Maps** for snapshots and starting-pose confirmation; **Settings** for planners and controllers. Motion status, drive mode and pause remain accessible outside the tabs. Flat cards, consistent spacing and labeled fields replace the long ungrouped controls list.

## Save a measured map

1. Open a navigation project and start the graph.
2. Drive or explore until the measured map contains the area you need.
3. Open **Maps**, give the map a name, and select **Capture map**.
4. Use the main **Save project** button to download the project. Capturing alone does not write a file.

A version 4 project embeds the occupancy grid, resolution, origin, environment configuration, capture pose and associated home poses. Existing embedded robot meshes remain supported. Projects without maps continue to export as version 2 or 3, and versions 1-3 can still be opened. Older Studio versions cannot open version 4 projects.

The snapshot is explicit: later mapping does not silently alter it. Select **Update map snapshot** and save the project again to refresh it. An explicitly configured navigation home takes precedence over the session home captured in a snapshot.

## Open and use a saved map

1. Stop the graph and use **Open project**.
2. Open **Maps**. Inspect the saved occupancy preview; its marker shows the pose at capture, not current localization.
3. Enter the robot's actual starting X, Y and yaw in the saved map coordinate system, then select **Confirm starting pose**. Built-in simulation starts at (0, 0, 0); do not use the capture pose merely because it is stored.
4. Start the graph. The saved occupancy is restored as a mapping prior and subsequent measurements update the live map.

Confirmation is deliberately session-only. Stopping/restarting or reopening requires it again. Startup fails before releasing staged device outputs if a saved map lacks confirmation. Initial positions outside measured free space or inside obstacle clearance are rejected. Removing a saved map requires a stopped graph and resets connected navigation homes for a fresh run.

Changing map geometry or the simulated environment while retaining an incompatible snapshot is rejected. Remove the snapshot first when intentionally starting a different map. A captured grid belongs to its SLAM node; a project can contain up to 16 snapshots, each at most 512 by 512 cells.

## Limits

This is **map persistence with operator initialization**, not automatic relocalization. The operator-supplied pose is not a confidence score or a sensor-verified match. Scan keyframes, loop-closure history and a localization confidence model are not persisted; local scan-to-submap mapping builds new anchors after startup. Unknown cells remain unknown. A matching environment configuration does not prove that a physical environment has not changed.

Next milestones are localization confidence, stopping when confidence is inadequate, and sensor-based relocalization against the stored map. Those must be tested before unattended restart-and-return operation is considered supported.

## Verification

`tests/test_map_persistence.py` covers malformed snapshots, configuration mismatch, explicit pose requirements, actual graph-start rejection without confirmation, occupancy restoration, API/project round trips, and snapshot removal. `tests/browser_simulation.py` exercises the new tabs and the capture/save/open/confirm/start/remove workflow. Screenshots are written to `artifacts/map-workspace.png` and `artifacts/four-wheel-studio.png`.

Local verification: all 28 regression scripts passed, followed by focused saved-map checks after the final validation changes. The final frontend build and browser workflow passed. Frontend lint reports only the three existing warnings in GridToolbar, PluginBuilder and useGraph; there are no new lint errors. Saved-map operation has not yet been checked in Webots or on hardware.
