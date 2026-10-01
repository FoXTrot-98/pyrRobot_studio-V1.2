# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Optional browser smoke test. Requires playwright and installed Microsoft Edge.

Starts isolated backend/frontend processes and always terminates its own servers.
Run separately from run_all.py: python tests/browser_simulation.py
"""
from pathlib import Path
import os
import subprocess
import sys
import json
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def ready(url, process):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Server exited with {process.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(.2)
    raise TimeoutError(url)


def main():
    from playwright.sync_api import sync_playwright
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    environment = dict(os.environ, PYROBOT_BUS_PUB="tcp://127.0.0.1:5575",
        PYROBOT_BUS_SUB="tcp://127.0.0.1:5576", PYROBOT_RERUN_GRPC_PORT="9986",
        PYROBOT_RERUN_WEB_PORT="9190", VITE_BACKEND_URL="http://127.0.0.1:8011",
        PYROBOT_STUDIO_ORIGINS="http://127.0.0.1:5175,http://localhost:5175")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    processes = []
    try:
        with (artifacts/"browser-servers.log").open("w",encoding="utf-8") as output:
            backend = subprocess.Popen([sys.executable,"-m","uvicorn","backend.app.main:app","--host","127.0.0.1","--port","8011"],
                cwd=ROOT,env=environment,stdout=output,stderr=output,creationflags=flags)
            processes.append(backend)
            frontend = subprocess.Popen(["node",str(ROOT/"frontend/node_modules/vite/bin/vite.js"),"--host","127.0.0.1","--port","5175","--strictPort"],
                cwd=ROOT/"frontend",env=environment,stdout=output,stderr=output,creationflags=flags)
            processes.append(frontend)
            ready("http://127.0.0.1:8011/api/plugins",backend)
            ready("http://127.0.0.1:5175",frontend)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="msedge",headless=True,
                    args=["--enable-unsafe-webgpu","--enable-unsafe-swiftshader","--use-angle=swiftshader","--ignore-gpu-blocklist"])
                page = browser.new_page(viewport={"width":1680,"height":1050})
                errors = []
                page.on("pageerror",lambda error: errors.append(str(error)))
                page.on("console",lambda msg: print(f"BROWSER {msg.type}: {msg.text}") if msg.type=="error" else None)
                page.goto("http://127.0.0.1:5175")
                page.locator('input[accept=".json,.pyrobot"]').set_input_files(str(ROOT/"examples/four-wheel/teleoperation.pyrobot.json"))
                page.evaluate("""() => {
                    window.robotMessages = {};
                    window.robotHistory = [];
                    window.robotSocket = new WebSocket('ws://127.0.0.1:8011/ws/bus');
                    window.robotSocket.onmessage = (event) => { const m=JSON.parse(event.data); window.robotMessages[m.topic]=m.payload;
                        if (['node/nav/out/path','node/sim/out/truth'].includes(m.topic)) {
                            window.robotHistory.push({topic:m.topic,payload:m.payload,command:window.robotMessages['node/drive/out/cmd_vel']});
                            if(window.robotHistory.length>1500) window.robotHistory.shift();
                        }
                    };
                }""")
                page.get_by_role("button",name="Start Graph",exact=True).click()
                page.get_by_role("button",name="Stop Graph",exact=True).wait_for()
                page.wait_for_timeout(10000)
                panel = page.get_by_role("region",name="Robot simulation")
                assert panel.is_visible()
                frame = page.frame_locator('iframe[title="Rerun robot simulation"]')
                frame.locator("canvas").first.wait_for(timeout=30000)
                with page.expect_response(lambda response: response.request.method == "PATCH" and "/nodes/nav/params" in response.url) as home_update:
                    page.get_by_role("button",name="Set home here",exact=True).click()
                assert home_update.value.ok
                page.wait_for_function("window.robotMessages['node/nav/out/path']?.status === 'paused'")
                saved_home=page.request.get('http://127.0.0.1:8011/api/graph').json()
                assert len(next(n for n in saved_home['nodes'] if n['node_id']=='nav')['params']['home_pose'])==3
                page.get_by_role("button",name="Manual",exact=True).click()
                pad = page.get_by_role("group",name="Keyboard driving pad")
                page.wait_for_function("document.querySelector('.keyboard-pad')?.innerText.includes('Click here')")
                pad.click()
                page.keyboard.down("w")
                page.wait_for_function("window.robotMessages['node/keyboard/out/cmd_vel']?.linear > 0")
                page.wait_for_timeout(800)
                page.get_by_label("Goal X",exact=True).focus()  # Losing pad focus must release held keys.
                page.wait_for_function("window.robotMessages['node/keyboard/out/cmd_vel']?.linear === 0")
                page.keyboard.up("w")
                print("PASS: keyboard press and focus-loss stop", flush=True)
                page.get_by_role("button",name="Stop",exact=True).click()
                # Mixed manual/autonomous driving is the default regression.
                # An explicit restart remains available for isolated comparisons.
                if '--restart-after-manual' in sys.argv:
                    page.get_by_role("button",name="Stop Graph",exact=True).click()
                    page.get_by_role("button",name="Start Graph",exact=True).click()
                    page.get_by_role("button",name="Stop Graph",exact=True).wait_for()
                    page.wait_for_timeout(10000)
                page.get_by_role("tab",name="Settings",exact=True).click()
                for label, value in (("Planner","dijkstra"),("Controller","fuzzy")):
                    with page.expect_response(lambda response: response.request.method == "PATCH" and "/nodes/nav/params" in response.url) as update:
                        page.get_by_label(label,exact=True).select_option(value)
                    assert update.value.ok
                page.wait_for_function("window.robotMessages['node/nav/out/path']?.planner === 'dijkstra' && window.robotMessages['node/nav/out/path']?.controller === 'fuzzy'")
                page.get_by_role("tab",name="Navigate",exact=True).click()
                measured_map = page.get_by_role("img",name="Click SLAM map to add waypoint")
                box = measured_map.bounding_box()
                for x,y in ((.8,0),(.8,.8)):
                    measured_map.click(position={"x":(x+2.4)/(.12*108)*box["width"],
                        "y":(1-(y+2.4)/(.12*91))*box["height"]})
                page.get_by_role("button",name="Run waypoints",exact=True).click()
                page.wait_for_function("['mission_complete','navigation_failed','stalled'].includes(window.robotMessages['node/nav/out/path']?.status)", timeout=60000)
                navigation = page.evaluate("window.robotMessages['node/nav/out/path']")
                (artifacts/'browser-navigation-history.json').write_text(json.dumps(page.evaluate("window.robotHistory")),encoding='utf-8')
                if navigation['status'] != 'mission_complete':
                    (artifacts/'browser-navigation-failure.json').write_text(json.dumps(page.evaluate("window.robotMessages")),encoding='utf-8')
                assert navigation['status'] == 'mission_complete', navigation
                assert page.evaluate("window.robotMessages['node/sim/out/truth'].collisions") == 0
                page.get_by_role("button",name="Return home",exact=True).click()
                page.wait_for_function("window.robotMessages['node/nav/out/path']?.status === 'home_reached'",timeout=90000)
                page.get_by_text('Home reached. Robot stopped; this does not perform docking.').wait_for(state='visible')
                print('PASS: algorithm selectors, Dijkstra/fuzzy outbound mission, return home and heading alignment',flush=True)
                page.get_by_role("tab",name="Maps",exact=True).click()
                page.get_by_label("Map name",exact=True).fill("Browser room")
                page.get_by_role("button",name="Capture map",exact=True).click()
                page.get_by_role("img",name="Saved occupancy map",exact=True).wait_for()
                mapped_project=page.request.post("http://127.0.0.1:8011/api/project/export",data={"name":"Mapped browser robot","positions":{}}).json()
                assert mapped_project['schema_version']==4
                assert mapped_project['saved_maps']['slam']['name']=='Browser room'
                page.screenshot(path=str(artifacts/"map-workspace.png"),full_page=True)
                page.get_by_role("tab",name="Navigate",exact=True).click()
                page.screenshot(path=str(artifacts/"four-wheel-studio.png"),full_page=True)
                print("Simulation status:",page.locator(".simulation-status").inner_text())
                page.get_by_role("button",name="Pause motion",exact=True).click()
                page.wait_for_timeout(700)
                assert "paused" in page.locator(".simulation-status").inner_text()
                page.get_by_label("Goal X",exact=True).fill("7.5")
                page.get_by_label("Goal Y",exact=True).fill("5.5")
                page.get_by_role("button",name="Navigate",exact=True).click()
                page.wait_for_timeout(700)
                assert "paused" not in page.locator(".simulation-status").inner_text()
                page.get_by_role("button",name="Cancel mission",exact=True).click()
                page.wait_for_function("window.robotMessages['node/nav/out/path']?.mission_state === 'cancelled'")
                page.get_by_role("button",name="Navigate",exact=True).click()
                page.wait_for_function("window.robotMessages['node/nav/out/path']?.mission_state === 'running'")
                page.get_by_role("button",name="Stop Graph",exact=True).click()
                page.get_by_role("button",name="Start Graph",exact=True).wait_for()
                saved_path=artifacts/'browser-mapped.project.json'
                saved_path.write_text(json.dumps(mapped_project),encoding='utf-8')
                page.locator('input[accept=".json,.pyrobot"]').set_input_files(str(saved_path))
                page.get_by_role("tab",name="Maps",exact=True).click()
                page.get_by_role("img",name="Saved occupancy map",exact=True).wait_for()
                with page.expect_response(lambda response: response.request.method=="POST" and response.url.endswith('/maps/nav/initialize')) as initialized:
                    page.get_by_role("button",name="Confirm starting pose",exact=True).click()
                assert initialized.value.ok
                page.get_by_role("button",name="Start Graph",exact=True).click()
                page.get_by_role("button",name="Stop Graph",exact=True).wait_for()
                page.wait_for_timeout(2000)
                assert page.request.get('http://127.0.0.1:8011/api/graph').json()['running']
                page.get_by_role("button",name="Stop Graph",exact=True).click()
                page.get_by_role("button",name="Start Graph",exact=True).wait_for()
                page.get_by_role("button",name="Remove saved map and reset home",exact=True).click()
                page.get_by_role("img",name="Saved occupancy map",exact=True).wait_for(state='detached')
                print('PASS: map capture, version 4 export/open, pose confirmation, restored-map startup and removal',flush=True)
                page.get_by_role("button",name="Robot configuration",exact=True).click()
                editor = page.get_by_label("Robot configuration JSON", exact=True)
                configuration = json.loads(editor.input_value())
                configuration["mapping"]["width"] = 110
                editor.fill(json.dumps(configuration))
                page.get_by_role("button",name="Apply configuration",exact=True).click()
                editor.wait_for(state="detached")
                project = page.request.get("http://127.0.0.1:8011/api/project").json()
                assert project["robot_config"]["mapping"]["width"] == 110
                removed = page.request.delete("http://127.0.0.1:8011/api/graph/connections", data={
                    "from_node": "sim", "from_port": "sensors", "to_node": "encoders", "to_port": "sensors"})
                assert removed.ok
                page.get_by_role("button",name="Start Graph",exact=True).click()
                page.get_by_text("Preflight failed: Connect required input encoders.sensors", exact=True).wait_for()
                assert page.locator('.studio-node [role="status"]').count() == 7
                assert not errors, errors
                browser.close()
                print("PASS: keyboard focus/release, map-click waypoint mission, Rerun, pause/resume, mission cancellation/replacement, configuration and preflight")
    finally:
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
