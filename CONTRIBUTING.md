<!--
SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
SPDX-License-Identifier: Apache-2.0
-->

# Contributing to PyRobot Studio

PyRobot Studio was originally created by Kanishka Kularathna (FoXTrot-98).
Help with bug reports, documentation, tests, UI improvements and robotics
features is welcome. Start with the [README](README.md) and [roadmap](docs/ROADMAP.md).

## Propose a change

Open an issue in this repository with the problem, expected behavior and a
reproduction. For simulation reports include the robot, world, spawn, planner,
controller and relevant logs. Remove tokens, private paths and confidential models.
Discuss substantial architectural changes before implementing them.

Fork the repository, create a focused branch, and submit a pull request describing
the behavior before and after, how you checked it, and any remaining limitations.
Maintainers review changes before merging; a fork does not need permission.
Keep discussions respectful and technical, and give credit for others' work.

## Checks

Follow the README's locked installation instructions. From the repository root:

```powershell
.\.venv\Scripts\python.exe tests/check_licensing.py
.\.venv\Scripts\python.exe tests/run_all.py
cd frontend
npm.cmd run build
npm.cmd run lint
node tests/modelSurface.mjs
cd ..
```

Add a regression for a behavior fix. Run relevant Webots/browser checks for
integration changes and state which optional checks you could not run.
Do not weaken collision, clearance or failure assertions merely to pass a test.
Do not commit credentials, virtual environments, dependency directories, generated
simulation runs or private CAD files.

## Licensing and attribution

By intentionally submitting a contribution for inclusion, you offer it under
Apache-2.0 as described in section 5 of [LICENSE](LICENSE), unless explicitly
stated otherwise and agreed before inclusion. You retain your copyright;
contributing does not transfer ownership to the original creator.

Only submit material you are entitled to contribute. Preserve existing notices,
credit upstream work, and identify modifications in affected third-party files
as required by their licenses. Record third-party sources and licenses in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Do not put the founder's copyright
on code owned by another contributor or upstream project.

For your own new Python file, use your name and the actual publication year:

```python
# SPDX-FileCopyrightText: 2026 Your Name
# SPDX-License-Identifier: Apache-2.0
```

Use the appropriate comment syntax for other source formats. For JSON, CAD data
and other files without suitable comments, add an explicit path annotation to
`REUSE.toml`. Preserve mandatory first lines such as shebangs, XML declarations
and Webots format headers. See [licensing scope](docs/LICENSING.md).
