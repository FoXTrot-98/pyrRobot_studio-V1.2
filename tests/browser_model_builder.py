"""Optional OBJ-to-URDF browser workflow; no simulator or hardware is started."""
import io
import os
import re
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as ET
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
        with (artifacts / 'model-builder-browser.log').open('w', encoding='utf-8') as log:
            backend = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app.main:app', '--host', '127.0.0.1', '--port', '8022'], cwd=ROOT, env=env, stdout=log, stderr=log, creationflags=flags)
            processes.append(backend)
            frontend = subprocess.Popen(['node', str(ROOT / 'frontend/node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', '5186', '--strictPort'], cwd=ROOT / 'frontend', env=env, stdout=log, stderr=log, creationflags=flags)
            processes.append(frontend)
            ready('http://127.0.0.1:8022/api/plugins', backend)
            ready('http://127.0.0.1:5186', frontend)
            with sync_playwright() as p:
                browser = p.chromium.launch(channel='msedge', headless=True)
                page = browser.new_page(viewport={'width': 1700, 'height': 1100})
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.on('dialog', lambda dialog: dialog.accept())
                page.goto('http://127.0.0.1:5186')
                before = page.request.get('http://127.0.0.1:8022/api/project').json()
                page.get_by_role('button', name='Model Builder', exact=True).click()
                dialog = page.get_by_role('dialog', name='Robot Model Builder')
                dialog.get_by_label('Import OBJ', exact=True).set_input_files(ROOT / 'examples/model-builder/two-link-arm.obj')
                dialog.get_by_label(re.compile(r'arm \(2\)')).check()
                expect(dialog.get_by_label('Smooth shading', exact=True)).to_be_checked()
                expect(dialog.get_by_text(re.compile('Smooth rendering is unavailable'))).to_have_count(0)
                expect(dialog.get_by_label('Wireframe', exact=True)).not_to_be_checked()
                dialog.get_by_label('Wireframe', exact=True).check()
                dialog.get_by_label('Wireframe', exact=True).uncheck()
                dialog.get_by_label('Smooth shading', exact=True).uncheck()
                dialog.get_by_label('Smooth shading', exact=True).check()
                dialog.get_by_role('button', name='Create link from selection', exact=True).click()
                dialog.get_by_label('Link name', exact=True).fill('arm_link')
                dialog.get_by_label('Joint type', exact=True).select_option('revolute')
                dialog.get_by_label('Pivot position (m) X', exact=True).fill('0.1')
                dialog.get_by_label('Pivot position (m) Y', exact=True).fill('0')
                dialog.get_by_label('Pivot position (m) Z', exact=True).fill('0.15')
                slider = dialog.get_by_label('arm_link position', exact=True)
                slider.focus()
                slider.press('End')
                expect(slider).to_have_value('1.57')
                with page.expect_response(lambda r:'/api/model-builder/preview' in r.url and r.status==200):
                    dialog.get_by_role('button', name='Reset to zero pose', exact=True).click()
                dialog.get_by_role('checkbox', name='I checked scale and the root frame orientation (+X forward, +Z up)', exact=True).check()
                dialog.get_by_role('button', name='Validate URDF', exact=True).click()
                dialog.get_by_text('URDF generated. Review these limitations before physics use:', exact=True).wait_for()
                with page.expect_download() as pending:
                    dialog.get_by_role('button', name='Export URDF bundle', exact=True).click()
                archive = artifacts / 'browser-robot-model.zip'
                pending.value.save_as(archive)
                with zipfile.ZipFile(io.BytesIO(archive.read_bytes())) as z:
                    xml = ET.fromstring(z.read('robot.urdf'))
                    self_joint = xml.find('joint')
                    assert self_joint.get('type') == 'revolute'
                    assert self_joint.find('origin').get('xyz') == '0.1 0 0.15'
                    assert 'meshes/arm_link.stl' in z.namelist()
                    saved = artifacts / 'browser-robot-builder.json'
                    saved.write_bytes(z.read('robot-builder.json'))
                dialog.get_by_label('Open editable model', exact=True).set_input_files(saved)
                dialog.get_by_label('Active link', exact=True).select_option('arm_link')
                expect(dialog.get_by_label('Joint type', exact=True)).to_have_value('revolute')
                expect(dialog.get_by_label('Pivot position (m) X', exact=True)).to_have_value('0.1')
                dialog.evaluate('(element) => { element.scrollTop = 0; }')
                page.screenshot(path=str(artifacts / 'robot-model-builder.png'))
                dialog.get_by_role('button', name='Close', exact=True).click()
                assert page.request.get('http://127.0.0.1:8022/api/project').json() == before
                assert not errors, errors
                browser.close()
                print('PASS: OBJ import, component grouping, joint pivot/limits/motion, URDF+meshes export and editable-model reopen; live project unchanged', flush=True)
    finally:
        for process in reversed(processes):
            if process.poll() is None: process.terminate()
        for process in processes:
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)


if __name__ == '__main__': main()
