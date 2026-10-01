# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Optional browser test for plugin generation, tests and source packages."""
import os
import subprocess
import sys
from browser_simulation import ROOT, ready


def main():
    from playwright.sync_api import sync_playwright, expect
    artifacts = ROOT / 'artifacts'
    artifacts.mkdir(exist_ok=True)
    env = dict(os.environ, PYROBOT_BUS_PUB='tcp://127.0.0.1:5585', PYROBOT_BUS_SUB='tcp://127.0.0.1:5586',
               PYROBOT_RERUN_GRPC_PORT='9996', PYROBOT_RERUN_WEB_PORT='9196', VITE_BACKEND_URL='http://127.0.0.1:8022',
               PYROBOT_STUDIO_ORIGINS='http://127.0.0.1:5186', PYROBOT_STUDIO_TOKEN='')
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    processes = []
    try:
        with (artifacts / 'builder-browser.log').open('w', encoding='utf-8') as log:
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
                page.get_by_role('button', name='Plugin Builder', exact=True).click()
                dialog = page.get_by_role('dialog', name='Plugin Builder')
                dialog.get_by_label('Plugin slug', exact=True).fill('browser_draft')
                dialog.get_by_role('button', name='Add parameter', exact=True).click()
                dialog.get_by_role('button', name='Generate Python', exact=True).click()
                expect(dialog.get_by_label('Python source')).not_to_have_value('')
                assert dialog.get_by_role('button', name='Test plugin', exact=True).is_disabled()
                dialog.get_by_role('checkbox').last.check()
                dialog.get_by_role('button', name='Test plugin', exact=True).click()
                dialog.get_by_text('Test: passed', exact=True).wait_for(timeout=15000)
                expect(dialog.get_by_role('button', name='Install tested plugin', exact=True)).to_be_enabled()
                page.screenshot(path=str(artifacts / 'plugin-builder.png'))
                with page.expect_download() as download:
                    dialog.get_by_role('button', name='Export package', exact=True).click()
                package = artifacts / 'browser-plugin.pyrobot-plugin.json'
                download.value.save_as(package)
                original_source = dialog.get_by_label('Python source', exact=True).input_value()
                dialog.get_by_role('button', name='Close', exact=True).click()
                page.get_by_role('button', name='Plugin Builder', exact=True).click()
                expect(dialog.get_by_label('Plugin slug', exact=True)).to_have_value('browser_draft')
                expect(dialog.get_by_label('Python source', exact=True)).to_have_value(original_source)
                expect(dialog.get_by_role('button', name='Test plugin', exact=True)).to_be_disabled()
                dialog.get_by_label('Plugin slug', exact=True).fill('changed_draft')
                dialog.locator('input[type=file]').set_input_files(package)
                expect(dialog.get_by_label('Plugin slug', exact=True)).to_have_value('browser_draft')
                expect(dialog.get_by_role('button', name='Remove parameter', exact=True)).to_be_visible()
                expect(dialog.get_by_role('button', name='Test plugin', exact=True)).to_be_disabled()
                dialog.get_by_role('checkbox').last.check()
                dialog.get_by_label('Python source', exact=True).fill('while True: pass')
                dialog.get_by_role('button', name='Test plugin', exact=True).click()
                dialog.get_by_text('Test: running', exact=True).wait_for()
                dialog.get_by_role('button', name='Cancel test', exact=True).click()
                dialog.get_by_text('Test: cancelled', exact=True).wait_for()
                expect(dialog.get_by_role('button', name='Install tested plugin', exact=True)).to_be_disabled()
                dialog.get_by_role('button', name='Close', exact=True).click()
                assert not errors, errors
                browser.close()
                print('PASS: Plugin Builder generation, execution, draft persistence, full-form export/import, trust reset, cancel and install gating', flush=True)
    finally:
        for process in reversed(processes):
            if process.poll() is None: process.terminate()
        for process in processes:
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)


if __name__ == '__main__': main()
