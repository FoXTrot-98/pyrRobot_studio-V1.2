<!-- SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
SPDX-License-Identifier: Apache-2.0 -->

# Arrange your simulation workspace

Rerun, Robot controls and the SLAM waypoint map are independent panels. Open a
simulation project to see their title bars. Restart Studio after updating and
refresh the browser to load the new interface.

- **Drag the title bar** to pull a panel out of its dock and move it within Studio.
- **Float** opens it at its remembered floating size and position. Drag the lower
  right corner to resize it. The resize handle also accepts arrow keys.
- **Maximize** fills the Studio window; **Restore** returns to the prior layout.
- **Full screen** uses browser full screen. Press Esc to leave it.
- **Pop out** moves the panel into a separate browser window. Move that window to
  another monitor or maximize it using the operating system's controls.
- **Dock** returns it to its original place. Closing a detached window also
  returns its panel. **Reset panel layout** restores all three default docks.

Allow pop-ups for Studio if the browser blocks a new window. A blocked pop-up
leaves the original panel available and displays an explanation.

Floating positions and sizes are saved in this browser, separately from project
JSON. Pop-up windows are opened only by a user click; reloading does not create
new windows automatically. Layouts are clamped to the current window size to
keep panels accessible after changing monitors.

Detached panels share the original Studio session: map updates, waypoint drafts
and control changes stay synchronized. Keep the main Studio tab open. Reloading
or closing it closes its detached windows; a detached panel is not an independent
runtime. Losing keyboard-pad focus or closing its window releases held keys.
Closing a view does not stop an autonomous mission; use Stop or Stop Graph.

This first version covers the three simulation panels. The graph canvas, node
palette and inspector retain their existing layout. Custom tab groups, dragging
panels between dock slots, and shared project layout presets are not implemented.

## Verification

```powershell
.\.venv\Scripts\python.exe tests/browser_workspace.py
```

The optional Edge test starts isolated servers and a built-in simulation. It
checks drag/resize, reload persistence, maximize, full screen, shared waypoint
drafts, docking, pop-out closure, keyboard command release and parent cleanup.

On 2026-10-04 the panel-specific browser checks and frontend build passed.
The broader `browser_simulation.py` run initially stalled with zero drive output;
an immediate repeat passed navigation, return home and saved-map workflows.
The subsequent [navigation timing investigation](SIMULATION_PERFORMANCE.md#mixed-mode-navigation-stall-follow-up-2026-10-04)
reproduced delayed commands being rejected by the drive watchdog and corrected
broker forwarding and browser telemetry buffering. This is a separate runtime
fix; panel rearrangement itself does not change navigation behavior.
