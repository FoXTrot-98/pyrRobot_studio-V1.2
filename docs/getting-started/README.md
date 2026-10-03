<!-- SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
SPDX-License-Identifier: Apache-2.0 -->

# Visual getting-started guide

Open [the PDF](PyRobot-Studio-Getting-Started.pdf) to read or share the 11-page
guide. [The HTML edition](index.html) works offline with the adjacent `images`
folder and can be printed from a browser. Keep both together when sharing HTML.

Edit `index.html`, then rebuild from the repository root:

```powershell
.\.venv\Scripts\python.exe docs/getting-started/build.py
```

Requires the development environment's Playwright and installed Microsoft Edge.
The builder checks image loading and page overflow before producing the PDF.
To refresh Studio screenshots, add `--capture`. It launches its own backend and
frontend on ports 8022/5186 and uses bus ports 5585/5586 and Rerun 9996/9196.
Keep these ports free. It runs only the sample built-in simulation and closes
its own processes. The frontend dependencies must already be installed.

`images/placement.png` is from the real Webots placement browser test, not the
built-in capture script. Refresh it from `artifacts/world-placement-valid.png`
after running `tests/browser_robot_setup.py` with `PYROBOT_TEST_WORLD=1`.
All other screenshots were captured against the current UI for this guide.
No robot dimensions shown in screenshots are universal defaults for user CAD.

After editing, inspect the rendered pages and confirm that button names and
supported capabilities still match the application. Update the edition date
when the guide changes. The PDF is committed documentation, not a build cache.
