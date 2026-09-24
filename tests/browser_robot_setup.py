"""Optional guided setup UI test; owns isolated servers and a headless browser."""
import os
import subprocess
import sys
from browser_simulation import ROOT, ready


def main():
    from playwright.sync_api import sync_playwright
    artifacts=ROOT/'artifacts'; artifacts.mkdir(exist_ok=True)
    env=dict(os.environ,PYROBOT_BUS_PUB='tcp://127.0.0.1:5585',PYROBOT_BUS_SUB='tcp://127.0.0.1:5586',
             PYROBOT_RERUN_GRPC_PORT='9996',PYROBOT_RERUN_WEB_PORT='9196',VITE_BACKEND_URL='http://127.0.0.1:8022')
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    processes=[]
    try:
        with (artifacts/'setup-browser.log').open('w',encoding='utf-8') as log:
            backend=subprocess.Popen([sys.executable,'-m','uvicorn','backend.app.main:app','--host','127.0.0.1','--port','8022'],cwd=ROOT,env=env,stdout=log,stderr=log,creationflags=flags)
            processes.append(backend)
            frontend=subprocess.Popen(['node',str(ROOT/'frontend/node_modules/vite/bin/vite.js'),'--host','127.0.0.1','--port','5186','--strictPort'],cwd=ROOT/'frontend',env=env,stdout=log,stderr=log,creationflags=flags)
            processes.append(frontend)
            ready('http://127.0.0.1:8022/api/plugins',backend); ready('http://127.0.0.1:5186',frontend)
            with sync_playwright() as p:
                browser=p.chromium.launch(channel='msedge',headless=True,args=['--enable-unsafe-webgpu','--enable-unsafe-swiftshader','--use-angle=swiftshader','--ignore-gpu-blocklist'])
                page=browser.new_page(viewport={'width':1500,'height':1000})
                errors=[]; page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto('http://127.0.0.1:5186')
                page.get_by_role('button',name='Robot setup',exact=True).click()
                dialog=page.get_by_role('dialog',name='Set up your robot')
                dialog.get_by_role('button',name='Use sample robot').click()
                dialog.get_by_role('img',name='Robot URDF preview').wait_for()
                dialog.get_by_role('button',name='Next',exact=True).click()
                dialog.get_by_label('Left rear wheel').select_option('front_left_wheel_joint')
                dialog.get_by_role('button',name='Next',exact=True).click()
                dialog.get_by_role('button',name='Next',exact=True).click()
                dialog.get_by_role('button',name='Check setup').click()
                dialog.get_by_role('alert').wait_for()
                assert 'distinct' in dialog.get_by_role('alert').inner_text()
                assert page.request.get('http://127.0.0.1:8022/api/graph').json()['nodes']==[]
                dialog.get_by_role('button',name='Back',exact=True).click()
                dialog.get_by_role('button',name='Back',exact=True).click()
                dialog.get_by_label('Left rear wheel').select_option('rear_left_wheel_joint')
                dialog.get_by_role('button',name='Next',exact=True).click()
                dialog.get_by_role('button',name='Next',exact=True).click()
                dialog.get_by_label('Project name',exact=True).fill('Wizard robot')
                dialog.get_by_role('button',name='Check setup').click()
                dialog.get_by_text('Setup checked',exact=True).wait_for()
                page.screenshot(path=str(artifacts/'robot-setup-wizard.png'))
                dialog.get_by_role('button',name='Apply robot setup').click()
                dialog.wait_for(state='detached')
                graph=page.request.get('http://127.0.0.1:8022/api/graph').json()
                assert len(graph['nodes'])==7 and not graph['running']
                assert page.get_by_label('Project name',exact=True).input_value()=='Wizard robot'
                # Cancelling a draft does not change the existing robot config.
                before=page.request.get('http://127.0.0.1:8022/api/project').json()
                page.get_by_role('button',name='Robot setup',exact=True).click()
                dialog.get_by_role('button',name='Next',exact=True).click()
                dialog.get_by_label('Encoder ticks per revolution').fill('8192')
                dialog.get_by_role('button',name='Cancel',exact=True).click()
                assert page.request.get('http://127.0.0.1:8022/api/project').json()==before
                # New graph replacement requires an explicit review acknowledgement.
                page.get_by_role('button',name='Robot setup',exact=True).click()
                for heading in ('How does your robot move?', 'Where are your sensors?', 'Review and create'):
                    dialog.get_by_role('button',name='Next',exact=True).click()
                    dialog.get_by_role('heading',name=heading,exact=True).wait_for()
                dialog.get_by_label('Project setup',exact=True).select_option('builtin')
                dialog.get_by_role('button',name='Check setup').click()
                dialog.get_by_text('Setup checked',exact=True).wait_for()
                assert dialog.get_by_role('button',name='Apply robot setup').is_disabled()
                dialog.get_by_role('button',name='Cancel',exact=True).click()
                page.get_by_role('button',name='Start Graph',exact=True).click()
                page.get_by_role('button',name='Stop Graph',exact=True).wait_for()
                assert page.get_by_role('button',name='Robot setup',exact=True).is_disabled()
                page.get_by_role('button',name='Stop Graph',exact=True).click()
                page.get_by_role('button',name='Start Graph',exact=True).wait_for()
                assert not errors,errors
                print('PASS: guided setup preview, invalid assignments, apply, cancel, replacement acknowledgement and graph startup',flush=True)
                browser.close()
    finally:
        for process in reversed(processes):
            if process.poll() is None: process.terminate()
        for process in processes:
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)


if __name__=='__main__': main()
