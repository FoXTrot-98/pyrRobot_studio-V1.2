# Connect and deploy to a robot computer

Studio's **Deploy** screen connects to a separate PyRobot agent. It checks a snapshot of the current project against the robot's installed plugins and configuration, transfers it, starts/stops the remote graph, and reads node health and recent agent logs. Manual address connection is supported; automatic network discovery is a future feature.

## Prepare the robot

Install this same project revision and its Python requirements on the robot computer. Its plugins, device drivers, external model files and simulation assets must be installed there. Project transfer sends JSON with embedded URDF, graph, parameters and layout, not Python code, dependencies or external assets. Different operating systems may need different serial ports and file paths in node settings.

From the project root, activate its virtual environment and create a random token:

```powershell
.\.venv\Scripts\Activate.ps1
$env:PYROBOT_AGENT_TOKEN = python -c "import secrets; print(secrets.token_urlsafe(32))"
$env:PYROBOT_AGENT_TOKEN
python -m core.runtime.agent
```

The agent listens on `127.0.0.1:8765`. Copy the value of `PYROBOT_AGENT_TOKEN` into Studio's password field. Tokens stay in browser memory and are cleared when the dialog closes; they are not saved in project files. Keep the agent terminal open. On Linux, use `source .venv/bin/activate` and `export PYROBOT_AGENT_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"` before the same module command.

For initial testing on the same PC, open **Deploy**, enter `http://127.0.0.1:8765` and the token, then **Connect**. The agent uses separate loopback bus ports 5595/5596 so it can coexist with Studio. Only one default agent can run per computer.

## Connect to a different computer

Keep the agent bound to loopback and use SSH forwarding from the Studio PC:

```powershell
ssh -N -L 8765:127.0.0.1:8765 username@robot-address
```

Then use `http://127.0.0.1:8765` in Studio. This requires an SSH server and account on the robot. For direct LAN access, configure a trusted TLS certificate:

```powershell
python -m core.runtime.agent --host 0.0.0.0 --certfile robot-cert.pem --keyfile robot-key.pem
```

Use the certificate's HTTPS hostname in Studio. Do not expose the ordinary Studio backend as a robot agent. The agent rejects non-loopback listening without TLS; the browser screen likewise refuses plaintext remote addresses. For a Studio origin other than `http://localhost:5173` or `http://127.0.0.1:5173`, pass `--origin` with the actual browser origin. Repeat it for multiple origins. HTTPS-hosted Studio may need an HTTPS agent because of browser mixed-content rules.

## Transfer and run

1. **Connect** and verify the robot hostname, OS and Python information.
2. **Check current project**. This takes a fixed snapshot and checks installed plugin versions, graph ports, required inputs and plugin configuration on the target. It does not prove physical device access or correct wiring.
3. Stop any existing remote graph, acknowledge replacement, then **Transfer project**. Compatibility is checked again on transfer. A rejected project leaves the previous graph available.
4. **Start remote** explicitly starts the transferred revision. **Refresh status and logs** reads node states, failure information and the last 400 Python log entries. Subprocess-specific logs such as Webots still reside in their documented artifact directories.
5. **Stop remote** shuts down the graph. Closing the dialog or losing the browser connection does not stop an autonomous project. Network loss also prevents remote stop: real hardware still requires local watchdogs and a physical emergency stop.

Accepted files are stored by SHA-256 revision under `artifacts/deployments/`. On restart the agent verifies the selected file's checksum and compatibility, and restores the project **stopped**. Recovery failure is logged and leaves no project started. Explicit Start is always required. Persistent rotating logs are stored as `agent.log` and four backups in that directory. Start requests must match the current revision to prevent stale clients starting a different project. This version has one token with full control, no multi-user roles, service installer, rollback picker or automatic reconnect. Avoid simultaneous operators. A busy operation returns 503 after a bounded lock wait; this reports contention and does not terminate a hung plugin.

Firmware flashing is deliberately separate. No board firmware is flashed by deployment; supported-board selection, bootloader detection and recovery guidance remain future work.

## Verification

`python tests/run_all.py` includes agent authentication, compatibility, transfer, revision checks, start/stop, logs and invalid-upload preservation tests. `python tests/browser_deployment.py` runs an optional end-to-end browser check with a separate agent and fake sensor project (requires Playwright and Edge). Test real hardware with a non-actuating project first. Local software tests are not real robot qualification.
