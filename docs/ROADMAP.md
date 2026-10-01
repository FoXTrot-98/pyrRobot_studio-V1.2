<!--
SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
SPDX-License-Identifier: Apache-2.0
-->

# Roadmap

This is the current milestone list; implemented features are described in the
[README](../README.md). Items below are remaining work, not release promises.

1. Reproducible baseline: review/commit source, reconcile documentation, verify
   fresh dependency installation and checks from a clean checkout. Record results
   in `BASELINE_VERIFICATION.md`.
2. Daily usability: managed startup/shutdown, bundled desktop installer, project
   autosave, undo/redo and actionable diagnostics.
3. Runtime containment: isolated plugin workers, bounded startup/shutdown,
   owned-process cleanup and explicit overload/delivery policies.
4. One verified physical robot: measured geometry, exact device protocol
   adapters, actuator watchdogs, stop acknowledgements and fault-injection tests.
5. Portable deployment: plugin/dependency/asset bundles, rollback, service
   installation and simulation/hardware profiles sharing a processing graph.
6. Broader robotics: more drive models, general live transforms, stronger
   localization/navigation, recording UI and manipulation planning.
7. Later tools: supported-board firmware flashing and controlled AI assistance.

Windows clean-install verification is separate from Linux/ARM qualification.
Hardware/endurance testing and licensing review remain independent release gates.
