"""Optional browser + real agent test, using a non-actuating fake IMU project."""
import os
import secrets
import subprocess
import sys
import time
import urllib.request
from browser_simulation import ROOT, ready


def main():
    from playwright.sync_api import sync_playwright
    token = secrets.token_urlsafe(32)
    studio_token = secrets.token_urlsafe(32)
    artifacts = ROOT / 'artifacts'
    artifacts.mkdir(exist_ok=True)
    env = dict(os.environ, PYROBOT_BUS_PUB='tcp://127.0.0.1:5585', PYROBOT_BUS_SUB='tcp://127.0.0.1:5586',
               PYROBOT_RERUN_GRPC_PORT='9996', PYROBOT_RERUN_WEB_PORT='9196',
               VITE_BACKEND_URL='http://127.0.0.1:8022', PYROBOT_AGENT_TOKEN=token,
               PYROBOT_STUDIO_ORIGINS='http://127.0.0.1:5186', PYROBOT_STUDIO_TOKEN=studio_token)
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    processes = []
    try:
        with (artifacts / 'deployment-browser.log').open('w', encoding='utf-8') as log:
            def launch(command, cwd=ROOT):
                process = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=log, creationflags=flags)
                processes.append(process)
                return process
            backend = launch([sys.executable, '-m', 'uvicorn', 'backend.app.main:app', '--host', '127.0.0.1', '--port', '8022'])
            frontend = launch(['node', str(ROOT / 'frontend/node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', '5186', '--strictPort'], ROOT / 'frontend')
            agent = launch([sys.executable, '-m', 'core.runtime.agent', '--port', '8767', '--origin', 'http://127.0.0.1:5186', '--directory', str(artifacts / 'deployment-browser-projects')])
            for _ in range(200):
                assert backend.poll() is None, 'Studio backend failed to start'
                try:
                    with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8022/api/plugins', headers={'Authorization': 'Bearer ' + studio_token}), timeout=1): break
                except OSError: time.sleep(.1)
            else: raise AssertionError('Studio backend did not become ready')
            ready('http://127.0.0.1:5186', frontend)
            for _ in range(100):
                assert agent.poll() is None, 'Agent failed to start; see deployment-browser.log'
                try:
                    with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8767/agent/status', headers={'Authorization': 'Bearer ' + token}), timeout=1): break
                except OSError: time.sleep(.1)
            else: raise AssertionError('Agent did not become ready')
            with sync_playwright() as p:
                browser = p.chromium.launch(channel='msedge', headless=True)
                page = browser.new_page(viewport={'width': 1700, 'height': 1000})
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                response = page.request.post('http://127.0.0.1:8022/api/project/import', headers={'Authorization': 'Bearer ' + studio_token}, data={
                    'format': 'pyrobot-project', 'schema_version': 2, 'name': 'Deployment browser test',
                    'robot_urdf': '<robot name="test"><link name="base_link"/></robot>',
                    'nodes': [{'node_id': 'imu', 'plugin_id': 'pyrobot.examples.fake_imu', 'plugin_version': '0.1.0', 'params': {}, 'urdf_link': 'base_link'}]})
                assert response.ok, response.text()
                page.goto('http://127.0.0.1:5186')
                page.get_by_label('Studio token', exact=True).fill(studio_token)
                page.get_by_role('button', name='Connect', exact=True).click()
                page.get_by_text('bus·connected', exact=True).wait_for()
                page.get_by_role('button', name='Deploy', exact=True).click()
                dialog = page.get_by_role('dialog', name='Robot connection and deployment')
                dialog.get_by_label('Agent address', exact=True).fill('http://127.0.0.1:8767')
                dialog.get_by_label('Agent token', exact=True).fill(token)
                dialog.get_by_role('button', name='Connect', exact=True).click()
                dialog.get_by_role('button', name='Check current project').click()
                dialog.get_by_text('Compatibility checks passed', exact=True).wait_for()
                assert dialog.get_by_role('button', name='Transfer project').is_disabled()
                dialog.get_by_label('Replace the stopped remote project with this snapshot').check()
                dialog.get_by_role('button', name='Transfer project').click()
                dialog.get_by_role('button', name='Start remote', exact=True).click()
                from playwright.sync_api import expect
                expect(dialog.get_by_role('button', name='Start remote', exact=True)).to_be_disabled()
                dialog.get_by_role('button', name='Refresh status and logs').click()
                expect(dialog.locator('pre')).to_contain_text('Remote graph started')
                dialog.get_by_role('button', name='Stop remote', exact=True).click()
                expect(dialog.get_by_role('button', name='Start remote', exact=True)).to_be_enabled()
                dialog.get_by_role('button', name='Refresh status and logs').click()
                expect(dialog.locator('pre')).to_contain_text('Remote graph stopped')
                dialog.get_by_role('button', name='Disconnect', exact=True).click()
                expect(dialog.get_by_label('Agent token', exact=True)).to_have_value('')
                assert not errors, errors
                browser.close()
                print('PASS: authenticated Studio HTTP/WebSocket login; agent connect, check, transfer, start, health/logs, stop and credential clearing', flush=True)
    finally:
        for process in reversed(processes):
            if process.poll() is None: process.terminate()
        for process in processes:
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)


if __name__ == '__main__': main()
