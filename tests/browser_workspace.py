# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Real browser checks for panel movement, persistence and shared pop-out state."""
import json
import os
import subprocess
import sys
from browser_simulation import ROOT, ready


def main():
    from playwright.sync_api import sync_playwright, expect
    env=dict(os.environ,PYROBOT_BUS_PUB='tcp://127.0.0.1:5585',PYROBOT_BUS_SUB='tcp://127.0.0.1:5586',
        PYROBOT_RERUN_GRPC_PORT='9996',PYROBOT_RERUN_WEB_PORT='9196',VITE_BACKEND_URL='http://127.0.0.1:8022',
        PYROBOT_STUDIO_ORIGINS='http://127.0.0.1:5186',PYROBOT_STUDIO_TOKEN='')
    processes=[]
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    artifacts=ROOT/'artifacts';artifacts.mkdir(exist_ok=True)
    try:
        with (artifacts/'workspace-browser.log').open('w',encoding='utf-8') as log:
            for command,cwd in (([sys.executable,'-m','uvicorn','backend.app.main:app','--host','127.0.0.1','--port','8022'],ROOT),
                (['node',str(ROOT/'frontend/node_modules/vite/bin/vite.js'),'--host','127.0.0.1','--port','5186','--strictPort'],ROOT/'frontend')):
                processes.append(subprocess.Popen(command,cwd=cwd,env=env,stdout=log,stderr=log,creationflags=flags))
            ready('http://127.0.0.1:8022/api/plugins',processes[0]);ready('http://127.0.0.1:5186',processes[1])
            with sync_playwright() as p:
                browser=p.chromium.launch(channel='msedge',headless=True,args=['--enable-unsafe-swiftshader','--use-angle=swiftshader'])
                page=browser.new_page(viewport={'width':1800,'height':1100})
                errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto('http://127.0.0.1:5186')
                response=page.request.post('http://127.0.0.1:8022/api/project/import',data=json.loads((ROOT/'examples/four-wheel/teleoperation.pyrobot.json').read_text()))
                assert response.ok,response.text()
                page.reload()
                slam=page.get_by_role('region',name='SLAM map panel',exact=True)
                slam.get_by_role('button',name='Float SLAM map',exact=True).click()
                expect(slam).to_have_class('workspace-panel floating  ')
                handle=slam.locator('.workspace-panel-title strong').bounding_box()
                before=slam.bounding_box()
                page.mouse.move(handle['x']+20,handle['y']+5);page.mouse.down();page.mouse.move(handle['x']+130,handle['y']+75);page.mouse.up()
                assert slam.bounding_box()['x']>before['x']+50
                size=slam.bounding_box()
                resize=slam.get_by_role('button',name='Resize SLAM map').bounding_box()
                page.mouse.move(resize['x']+8,resize['y']+8);page.mouse.down();page.mouse.move(resize['x']+85,resize['y']+55);page.mouse.up()
                assert slam.bounding_box()['width']>size['width']+40
                page.reload();expect(slam).to_have_class('workspace-panel floating  ')
                slam.get_by_role('button',name='Maximize SLAM map',exact=True).click()
                assert slam.bounding_box()['width']>1700
                slam.get_by_role('button',name='Restore SLAM map',exact=True).click()
                slam.get_by_role('button',name='Dock SLAM map',exact=True).click()
                page.evaluate("""() => {
                    window.robotMessages={};window.observer=new WebSocket('ws://127.0.0.1:8022/ws/bus');
                    window.observer.onmessage=e=>{const m=JSON.parse(e.data);window.robotMessages[m.topic]=m.payload;};
                }""")
                page.get_by_role('button',name='Start Graph',exact=True).click()
                page.get_by_role('button',name='Stop Graph',exact=True).wait_for()
                with page.expect_popup() as opening:slam.get_by_role('button',name='Pop out SLAM map',exact=True).click()
                popup=opening.value;popup.on('pageerror',lambda error:errors.append(str(error)))
                expect(popup.get_by_role('region',name='SLAM map panel',exact=True)).to_be_visible()
                popup.get_by_role('img',name='Click SLAM map to add waypoint').wait_for(timeout=30000)
                popup.get_by_role('img',name='Click SLAM map to add waypoint').click(position={'x':15,'y':15})
                expect(popup.get_by_text('1 waypoints',exact=False).first).to_be_visible()
                popup.get_by_role('button',name='Full screen SLAM map',exact=True).click()
                popup.wait_for_function('document.fullscreenElement !== null')
                popup.evaluate('document.exitFullscreen()')
                popup.screenshot(path=str(artifacts/'workspace-slam-popout.png'))
                popup.get_by_role('button',name='Dock SLAM map',exact=True).click()
                expect(slam).to_be_visible()
                expect(slam.get_by_text('1 waypoints',exact=False).first).to_be_visible()
                slam.get_by_role('button',name='Undo point',exact=True).click()
                # A browser-close also restores the panel, with the graph intact.
                with page.expect_popup() as opening:page.get_by_role('button',name='Pop out Robot controls',exact=True).click()
                controls=opening.value
                controls.get_by_role('button',name='Manual',exact=True).click()
                expect(controls.get_by_role('button',name='Manual',exact=True)).to_have_attribute('aria-pressed','true')
                pad=controls.get_by_role('group',name='Keyboard driving pad')
                pad.click();controls.keyboard.down('w')
                page.wait_for_function("window.robotMessages['node/keyboard/out/cmd_vel']?.linear>0")
                controls.close()
                page.wait_for_function("window.robotMessages['node/keyboard/out/cmd_vel']?.linear===0")
                expect(page.get_by_role('button',name='Manual',exact=True)).to_have_attribute('aria-pressed','true')
                assert page.request.get('http://127.0.0.1:8022/api/graph').json()['running']
                page.get_by_role('button',name='Reset panel layout',exact=True).click()
                assert page.locator('.workspace-panel.floating').count()==0
                page.screenshot(path=str(artifacts/'workspace-panels.png'))
                page.get_by_role('button',name='Stop Graph',exact=True).click()
                with page.expect_popup() as opening:page.get_by_role('button',name='Pop out Rerun',exact=True).click()
                rerun=opening.value
                expect(rerun.locator('iframe[title="Rerun robot simulation"]')).to_be_visible()
                page.reload()
                expect(rerun).to_have_url('about:blank') if not rerun.is_closed() else None
                page.wait_for_timeout(500)
                assert rerun.is_closed(),'Reload leaked detached viewer'
                assert not errors,errors
                browser.close()
                print('PASS panel drag/resize, persistence, maximize, pop-out, docking, close and shared controls')
    finally:
        for process in reversed(processes):
            if process.poll() is None:process.terminate()
        for process in processes:
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)


if __name__=='__main__':main()
