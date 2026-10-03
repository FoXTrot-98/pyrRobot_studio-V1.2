# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Optional real-Webots invalid placement -> retry -> apply -> sensor workflow."""
import argparse
import os
from pathlib import Path
import socket
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
for variable in ('PYROBOT_BUS_PUB','PYROBOT_BUS_SUB'):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        os.environ[variable]=f'tcp://127.0.0.1:{sock.getsockname()[1]}'

from fastapi.testclient import TestClient
from backend.app import main
import logging
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('pyrobot.graph').setLevel(logging.WARNING)


def run():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,default=ROOT/'examples/four-wheel/webots.pyrobot.json')
    parser.add_argument('--world',type=Path,default=ROOT/'tests/fixtures/external-room.wbt')
    parser.add_argument('--spawn',type=float,nargs=3,default=[1.,1.,0.])
    parser.add_argument('--search',action='store_true',help='Search from an unsafe initial X/Y at normal base height')
    args=parser.parse_args()
    with patch.object(main,'init_rerun'),TestClient(main.app) as client:
        def post(path,body):
            response=client.post(path,json=body)
            assert response.status_code==200,response.text
            return response.json()
        import json
        post('/api/project/import',json.loads(args.project.read_text(encoding='utf-8')))
        catalog=client.get('/api/simulation/worlds').json()
        choice=dict(path=str(args.world),revision=catalog['revision'],spawn_pose=args.spawn,
                    spawn_height=.002 if args.search else 1.,bounds=[-15,-15,15,15],resolution=.15,reset_mission=True)
        choice['source_hash']=post('/api/simulation/worlds/preview',choice)['sha256']
        assert client.post('/api/simulation/worlds/apply',json=choice).status_code==400
        def search():
            post('/api/simulation/worlds/placement/'+choice['placement_token']+'/search',{})
            deadline=time.monotonic()+150
            previous=None
            while True:
                result=main.placement_preview.status()
                progress=result.get('search',{})
                if progress!=previous:
                    print('Search',progress,flush=True);previous=progress
                assert result['status']!='failed',result
                assert progress.get('status')!='exhausted',result
                if progress.get('status')=='found':break
                assert time.monotonic()<deadline,result
                time.sleep(.2)
            assert client.post('/api/simulation/worlds/apply',json=choice).status_code==400

        def check(expected):
            token=post('/api/simulation/worlds/placement',choice)['token']
            deadline=time.monotonic()+90
            previous=None
            while time.monotonic()<deadline:
                result=client.get('/api/simulation/worlds/placement/'+token).json()
                description=(result['status'],result['reasons'])
                if description!=previous:
                    print(description,flush=True)
                    previous=description
                assert result['status']!='failed',result
                if result['status']==expected:
                    print(expected,result,flush=True)
                    return token
                time.sleep(.2)
            raise AssertionError(result)

        choice['placement_token']=check('invalid')
        invalid_process=main.placement_preview.node._process
        assert invalid_process.poll() is None,'Invalid preview must stay open'
        assert client.post('/api/simulation/worlds/apply',json=choice).status_code==400
        if args.search:search()
        deadline=time.monotonic()+15
        while True:
            settled=main.placement_preview.status()
            if settled.get('can_use_observed'):break
            assert time.monotonic()<deadline,settled
            time.sleep(.1)
        # Same explicit adoption as Studio's Use Webots position button.
        x,y,z=settled['observed_position']
        choice['spawn_pose']=[x,y,settled['observed_yaw']]
        choice['spawn_height']=z
        choice['placement_token']=check('valid')
        assert invalid_process.poll() is not None,'Retry leaked previous process'
        process=main.placement_preview.node._process
        stale={**choice,'spawn_pose':[args.spawn[0]+.1,*args.spawn[1:]]}
        assert client.post('/api/simulation/worlds/apply',json=stale).status_code==400
        post('/api/simulation/worlds/apply',choice)
        assert process.poll() is not None,'Apply leaked preview process'
        assert main.placement_preview is None
        received={}
        handle=main.runtime.bus.subscribe('node/',lambda message:received.update({message.topic:message.payload}))
        try:
            post('/api/graph/start',{})
            deadline=time.monotonic()+90
            while 'node/sim/out/camera' not in received or 'node/slam/out/state' not in received:
                graph=main.runtime.graph.to_dict()
                assert not graph['failure_reason'],graph
                assert time.monotonic()<deadline,'Sensors timed out'
                time.sleep(.1)
            assert received['node/sim/out/sensors']['time']>=2,'Published before settling'
            print('PASS placement rejection, retained preview, retry, stale receipt, cleanup and sensor startup',flush=True)
        finally:
            post('/api/graph/stop',{})
            handle.close()


if __name__=='__main__':run()
