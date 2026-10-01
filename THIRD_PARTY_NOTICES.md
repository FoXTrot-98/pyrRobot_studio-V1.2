<!--
SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
SPDX-License-Identifier: Apache-2.0
-->

# Third-party notices

## Vite template material (MIT)

Copyright (c) 2019-present, VoidZero Inc. and Vite contributors.
The full permission and warranty notice is in [LICENSES/MIT.txt](LICENSES/MIT.txt).

The following bundled graphics match the Vite React/TypeScript template
(ignoring line endings and outer whitespace):

- `frontend/public/favicon.svg`
- `frontend/public/icons.svg`

Verified against Vite commit `ede50985fbe0f5a20cf33f0cde30633f2923c85e`:
[template source](https://github.com/vitejs/vite/tree/ede50985fbe0f5a20cf33f0cde30633f2923c85e/packages/create-vite/template-react-ts).
The graphics retain upstream MIT attribution; they are not claimed as the
PyRobot Studio creator's artwork. Brand names/logos do not imply endorsement.

Vite-derived scaffolding is conservatively covered by both the upstream MIT
notice and Apache-2.0 for project modifications: `frontend/index.html`,
`frontend/vite.config.ts`, `frontend/src/vite-env.d.ts`, and
`frontend/tsconfig*.json`. See their headers and `REUSE.toml`.

## Installed dependencies and external resources

Python and npm dependencies retain their own licenses. This project's Apache
license does not relicense them. Dependencies are installed from
`requirements.lock.txt` and `frontend/package-lock.json`; their metadata and
license files must be reviewed when assembling a binary or bundled distribution.
This file is not a complete transitive dependency license audit.

Webots, its installed example worlds/PROTOs, browser installations and externally
loaded CAD/world assets are not included under the project license. Verify the
rights to redistribute those resources separately. Example project configurations
that select Webots robots do not transfer ownership of the external robot assets.

The frontend requests Space Grotesk and JetBrains Mono through Google Fonts;
font files are not vendored here. Preserve their own notices if bundling them.
