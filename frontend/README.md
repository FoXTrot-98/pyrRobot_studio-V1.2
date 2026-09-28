# PyRobot Studio frontend

React/TypeScript Studio UI for the FastAPI backend. Follow the root
[README](../README.md) for installation and startup; it specifies the baseline
Python/Node versions and uses `npm ci` with the committed lockfile.

From this directory:

```powershell
npm.cmd ci
npm.cmd run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

The backend must run on port 8000. Custom endpoints/origins are documented in
`.env.example` and [industrial readiness](../docs/INDUSTRIAL_READINESS.md).

Checks: `npm run build`, `npm run lint`, and `node tests/modelSurface.mjs`.
See [baseline verification](../docs/BASELINE.md) for optional browser workflows.
