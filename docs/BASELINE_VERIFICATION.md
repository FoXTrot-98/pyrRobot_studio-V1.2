# Baseline verification record

Date: 2026-09-28

## Revision and method

Source commit: `28917a568105a441f046b13a6e5937c5f8dc2ee2`.
The verification-record commit adds documentation only; application source,
fixtures, dependency locks and CI configuration remain at this tested revision.

Created a fresh local clone with `git clone --no-hardlinks . artifacts/baseline-checkout`.
Created its own `.venv` (system site packages disabled) and installed its own
`frontend/node_modules`. Neither installed environment was copied from the
working tree. Package download caches were reused. No car1 CAD file, SDK ZIP or
existing artifacts were needed for the baseline checks.

## Local environment

- Windows 11 x64, build 26200.
- Python 3.14.6, pip 26.1.2.
- Node.js 24.18.0, npm 11.16.0.
- Microsoft Edge available for the optional browser workflow.

## Results

| Check | Result |
| --- | --- |
| Install `requirements.lock.txt` into fresh venv | Passed; 48 pinned distributions match installed versions |
| `python -m pip check` | Passed; no broken requirements |
| `npm ci --no-audit --no-fund` | Passed; 78 packages installed |
| Frontend production build | Passed |
| Frontend lint | Passed with three existing warnings |
| `node tests/modelSurface.mjs` | Passed |
| Full Python suite, sequential rerun | Passed; all 22 scripts, zero failures |
| `tests/browser_model_builder.py` | Passed using the committed STEP and OBJ examples |
| CLI validate, four-wheel navigation example | Passed |
| CLI run, IMU example, two seconds | Passed on separately allocated loopback broker ports; clean shutdown |
| Verification checkout status | Clean after installation and checks; outputs are ignored |

The browser test covers server startup, STEP import and preview, OBJ editing,
export/reopen, setup handoff, bundle import, mesh simulation startup and embedded
project saving. It uses the fresh clone's backend and frontend dependencies.

## Observations and limits

The first Python suite run, concurrent with browser verification, had one failure
in Plugin Builder's timeout test. The other scripts passed. The isolated Plugin
Builder test subsequently passed (four tests, 20.7 seconds). The full sequential
rerun passed all 22 scripts with zero failures. No timeout assertion was
weakened to make the checks pass. The underlying cause of the first timing
failure has not been established.

The direct CLI run initially encountered an existing runtime on port 5555. It
was rerun with separate free ports without stopping the other runtime. Sandbox
restrictions also blocked Git cloning, virtual-environment bootstrap and Vite
child-process creation; those checks were rerun with the required permissions.
These environmental failures are distinct from application test failures.

Lint warnings remain in GridToolbar (component-only exports), useGraph and
PluginBuilder (state updates in effects). Windows skips the POSIX pseudo-terminal
test explicitly; serial loopback still runs. Linux/ARM, remote CI results,
offline installation, hash-verified dependencies and physical hardware remain
unverified. Real Webots/car1 checks from the earlier working tree are separate
from this fresh-install acceptance run.
