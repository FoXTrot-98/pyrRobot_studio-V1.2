"""Optional native-example picker browser test; does not launch a simulator."""
import os
import subprocess
import sys
from browser_simulation import ROOT, ready


def main():
    from playwright.sync_api import sync_playwright
    artifacts = ROOT / 'artifacts'
    artifacts.mkdir(exist_ok=True)
    env = dict(os.environ, PYROBOT_BUS_PUB='tcp://127.0.0.1:5585', PYROBOT_BUS_SUB='tcp://127.0.0.1:5586',
               PYROBOT_RERUN_GRPC_PORT='9996', PYROBOT_RERUN_WEB_PORT='9196', VITE_BACKEND_URL='http://127.0.0.1:8022', PYROBOT_STUDIO_ORIGINS='http://127.0.0.1:5186')
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    processes = []
    try:
        with (artifacts / 'examples-browser.log').open('w', encoding='utf-8') as log:
            backend = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app.main:app', '--host', '127.0.0.1', '--port', '8022'], cwd=ROOT, env=env, stdout=log, stderr=log, creationflags=flags)
            processes.append(backend)
            frontend = subprocess.Popen(['node', str(ROOT / 'frontend/node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', '5186', '--strictPort'], cwd=ROOT / 'frontend', env=env, stdout=log, stderr=log, creationflags=flags)
            processes.append(frontend)
            ready('http://127.0.0.1:8022/api/plugins', backend)
            ready('http://127.0.0.1:5186', frontend)
            with sync_playwright() as p:
                browser = p.chromium.launch(channel='msedge', headless=True)
                page = browser.new_page(viewport={'width': 1600, 'height': 1000})
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.on('dialog', lambda dialog: dialog.accept())
                page.goto('http://127.0.0.1:5186')
                for title, action in [('Panda robot arm', 'reach near'), ('NAO humanoid', 'wave'), ('KUKA youBot mobile manipulator', 'arm home')]:
                    page.get_by_role('button', name='Examples', exact=True).click()
                    dialog = page.get_by_role('dialog', name='Webots examples')
                    dialog.get_by_role('button', name='Open ' + title, exact=True).click()
                    dialog.wait_for(state='detached')
                    panel = page.get_by_role('region', name='Native Webots robot')
                    panel.get_by_role('button', name=action, exact=True).wait_for()
                    assert panel.get_by_role('button', name=action, exact=True).is_disabled()
                    assert page.get_by_label('Project name', exact=True).input_value() == title
                    graph = page.request.get('http://127.0.0.1:8022/api/graph').json()
                    assert not graph['running']
                    assert len(graph['nodes']) == (3 if 'youBot' in title else 2)
                assert panel.get_by_label('Manual driving', exact=True).is_disabled()
                page.screenshot(path=str(artifacts / 'webots-examples.png'))
                assert not errors, errors
                browser.close()
                print('PASS: three native example imports, project names, stopped controls and youBot keyboard panel', flush=True)
    finally:
        for process in reversed(processes):
            if process.poll() is None: process.terminate()
        for process in processes:
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)


if __name__ == '__main__': main()
