<!--
SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
SPDX-License-Identifier: Apache-2.0
-->

# Licensing and attribution

Project-owned PyRobot Studio code, documentation and examples are offered under
the [Apache License 2.0](../LICENSE). Original creator:
**Kanishka Kularathna ([FoXTrot-98](https://github.com/FoXTrot-98))**.
See [NOTICE](../NOTICE) and [AUTHORS.md](../AUTHORS.md).

## File coverage

Source and documentation files carry SPDX copyright/license comments. Files
whose formats should not receive comments (including JSON, lockfiles, version
files and the STEP example) have explicit path annotations in `REUSE.toml`.
There is no repository-wide wildcard that would automatically claim ownership
of future third-party additions. License texts are kept verbatim in `LICENSE`
and `LICENSES/`; the Apache text is duplicated there for REUSE tooling.

Vite template graphics retain MIT attribution. Vite-derived frontend scaffolding
retains the upstream MIT notice alongside Apache-2.0 for project modifications.
See [third-party notices](../THIRD_PARTY_NOTICES.md).

The initial review examined tracked files, existing notice markers, Git author
history and the two template graphics' upstream contents. First-party notices
reflect the maintainer's declaration of ownership of the project material;
Git history and file inspection cannot independently establish ownership of
every contribution or CAD asset. Correct any previously unrecorded upstream
source before distributing that material. No ownership is asserted over ignored
local artifacts, imported private models or installed dependencies.

## Community changes

Preserve relevant copyright and attribution notices when redistributing, include
the applicable licenses, retain applicable NOTICE attribution, and identify
modified files as Apache-2.0 requires. The license permits commercial use and
proprietary derivatives; it does not require forks to contribute back or display
the founder's name in their application UI. Creator credit is included in the
official project's README and Studio interface.

New contributors should identify themselves on their own work and preserve prior
notices on modified files. See [CONTRIBUTING.md](../CONTRIBUTING.md).

## Verification

Run `python tests/check_licensing.py` to check coverage of tracked and unignored
new files, license identifiers, known upstream notices and synchronized Apache
texts. CI runs the same check. This is a lightweight repository check, not a
legal provenance determination or a substitute for a dependency/license audit
when distributing packaged software. Standard REUSE tools can also consume the
SPDX headers, `REUSE.toml` and `LICENSES/` directory.
