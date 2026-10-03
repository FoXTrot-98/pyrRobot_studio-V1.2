# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Build the printable guide with Edge; --capture refreshes Studio screenshots."""
import argparse
import os
import re
from pathlib import Path
import subprocess
import sys
from playwright.sync_api import sync_playwright

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from browser_simulation import ready


def capture(browser):
    env=dict(os.environ,PYROBOT_BUS_PUB='tcp://127.0.0.1:5585',PYROBOT_BUS_SUB='tcp://127.0.0.1:5586',
        PYROBOT_RERUN_GRPC_PORT='9996',PYROBOT_RERUN_WEB_PORT='9196',
        VITE_BACKEND_URL='http://127.0.0.1:8022',PYROBOT_STUDIO_ORIGINS='http://127.0.0.1:5186',PYROBOT_STUDIO_TOKEN='')
    processes=[]
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    (HERE/'images').mkdir(exist_ok=True)
    (ROOT/'artifacts').mkdir(exist_ok=True)
    try:
        with (ROOT/'artifacts/guide-capture.log').open('w',encoding='utf-8') as log:
            for command,cwd in (([sys.executable,'-m','uvicorn','backend.app.main:app','--host','127.0.0.1','--port','8022'],ROOT),
                (['node',str(ROOT/'frontend/node_modules/vite/bin/vite.js'),'--host','127.0.0.1','--port','5186','--strictPort'],ROOT/'frontend')):
                processes.append(subprocess.Popen(command,cwd=cwd,env=env,stdout=log,stderr=log,creationflags=flags))
            ready('http://127.0.0.1:8022/api/plugins',processes[0]);ready('http://127.0.0.1:5186',processes[1])
            page=browser.new_page(viewport={'width':1500,'height':1050})
            page.goto('http://127.0.0.1:5186')
            page.get_by_role('button',name='Robot setup',exact=True).wait_for()
            page.screenshot(path=str(HERE/'images/workspace.png'))
            page.get_by_role('button',name='Model Builder',exact=True).click()
            builder=page.get_by_role('dialog',name='Robot Model Builder')
            builder.get_by_label('Open editable model',exact=True).set_input_files(ROOT/'examples/model-builder/four-wheel-rover.robot-builder.json')
            page.wait_for_timeout(1500)
            builder.screenshot(path=str(HERE/'images/builder.png'))
            builder.get_by_role('button',name='Close',exact=True).click()
            page.get_by_role('button',name='Robot setup',exact=True).click()
            dialog=page.get_by_role('dialog',name='Set up your robot')
            dialog.get_by_role('button',name='Use sample robot').click()
            dialog.get_by_role('img',name='Robot URDF preview').wait_for()
            dialog.screenshot(path=str(HERE/'images/model.png'))
            dialog.get_by_role('button',name='Next',exact=True).click()
            dialog.screenshot(path=str(HERE/'images/drive.png'))
            dialog.get_by_role('button',name='Next',exact=True).click()
            dialog.screenshot(path=str(HERE/'images/sensors.png'))
            dialog.get_by_role('button',name='Next',exact=True).click()
            dialog.get_by_label('Project name',exact=True).fill('My first robot')
            dialog.get_by_role('button',name='Check setup',exact=True).click()
            dialog.get_by_text('Setup checked',exact=True).wait_for()
            dialog.screenshot(path=str(HERE/'images/review.png'))
            dialog.get_by_role('button',name='Apply robot setup',exact=True).click()
            dialog.wait_for(state='detached')
            page.get_by_role('button',name='World setup',exact=True).click()
            world=page.get_by_role('dialog',name='World setup',exact=True)
            world.screenshot(path=str(HERE/'images/world.png'))
            page.get_by_role('button',name='Close world setup').click()
            page.get_by_role('button',name='Start Graph',exact=True).click()
            page.get_by_role('button',name='Stop Graph',exact=True).wait_for()
            page.get_by_role('button',name='Manual',exact=True).click()
            page.wait_for_timeout(4000)
            page.get_by_role('complementary',name='Map and robot controls').screenshot(path=str(HERE/'images/controls.png'))
            page.get_by_role('tab',name='Maps',exact=True).click()
            page.get_by_role('tabpanel',name='Maps',exact=True).screenshot(path=str(HERE/'images/maps.png'))
            page.get_by_role('button',name='Stop Graph',exact=True).click()
            page.close()
    finally:
        for process in reversed(processes):
            if process.poll() is None:process.terminate()
        for process in processes:
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture',action='store_true')
    args=parser.parse_args()
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True,args=['--enable-unsafe-swiftshader','--use-angle=swiftshader'])
        try:
            if args.capture:capture(browser)
            page=browser.new_page(viewport={'width':1000,'height':1400})
            page.goto((HERE/'index.html').as_uri())
            page.evaluate('() => Promise.all([...document.images].map(i => i.decode()))')
            overflow=page.locator('section.page').evaluate_all('(pages) => pages.map((p,i)=>({page:i+1,overflow:p.scrollHeight>p.clientHeight+2 || p.lastElementChild.getBoundingClientRect().bottom>p.getBoundingClientRect().bottom-70})).filter(p=>p.overflow)')
            if overflow:raise RuntimeError(f'Guide page overflow: {overflow}')
            page.pdf(path=str(HERE/'PyRobot-Studio-Getting-Started.pdf'),format='A4',print_background=True,prefer_css_page_size=True)
            pdf=(HERE/'PyRobot-Studio-Getting-Started.pdf').read_bytes()
            if len(re.findall(rb'/Type\s*/Page\b',pdf))!=page.locator('section.page').count():
                raise RuntimeError('PDF page count differs from source; inspect print margins')
            for index in range(page.locator('section.page').count()):
                page.locator('section.page').nth(index).screenshot(path=str(ROOT/f'artifacts/guide-page-{index+1}.png'))
            print(f'Built {page.locator("section.page").count()} pages: {HERE / "PyRobot-Studio-Getting-Started.pdf"}')
        finally:browser.close()


if __name__=='__main__':main()
