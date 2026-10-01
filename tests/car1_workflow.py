# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Opt-in car1 integration test; estimated CAD setup, never physical hardware.

Run after import, or use --import-step to rebuild the cached editable model.
The exported project is a simulation draft: verify wheel/sensor calibration.
"""
import argparse
import json
import logging
import math
from pathlib import Path
import sys
import time
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.urdf.builder import Model, Link, bundle
from core.urdf.cad import import_step
from core.simulation.config import RobotConfiguration
from core.simulation.webots_project import generate_project
from fastapi.testclient import TestClient
from backend.app import main


def checked(response):
    assert response.status_code == 200, response.text
    return response.json()


def main_test():
    parser = argparse.ArgumentParser()
    parser.add_argument('--import-step', action='store_true')
    args = parser.parse_args()
    out = ROOT / 'artifacts/car1'
    out.mkdir(parents=True, exist_ok=True)
    source = out / 'imported.robot-builder.json'
    if args.import_step:
        model = import_step((ROOT/'tests/fixtures/car1.STEP').read_bytes(), filename='car1.STEP')
        source.write_text(model.model_dump_json(), encoding='utf-8')
    model = Model.model_validate_json(source.read_text(encoding='utf-8'))
    links = {link.name: link for link in model.links}
    parts = {part.id: part for part in model.parts}
    wheels = [links[name] for name in ['Wheel','Wheel_2','Wheel_3','Wheel_4']]
    radii = []
    for wheel in wheels:
        points = np.asarray(parts[wheel.parts[0]].vertices) * model.scale
        radii.append(float(np.linalg.norm(points[:,[0,2]]-np.asarray(wheel.xyz)[[0,2]],axis=1).max()))
        wheel.xyz[1] = float((points[:,1].min()+points[:,1].max())/2)
        wheel.kind = 'continuous'
        wheel.rpy = [0,0,math.pi]
        wheel.axis = [0,1,0]
    radius = float(np.median(radii))
    root = next(link for link in model.links if link.parent is None)
    root.xyz = np.mean([wheel.xyz for wheel in wheels], axis=0).tolist()
    root.xyz[2] -= radius
    root.rpy = [0,0,math.pi]  # CAD Front is at smaller X.
    for name, reference in [('test_lidar_frame','head'),('test_camera_frame','zedmini_camera')]:
        link = links[reference]
        points = np.asarray(parts[link.parts[0]].vertices) * model.scale
        position = (points.min(0)+points.max(0))/2
        # CAD shells are opaque to simulated sensors. These explicit test
        # mounts sit outside the shell; they are not optical calibration.
        if name == 'test_lidar_frame':
            position[2] = points[:,2].max() + .01
        else:
            position[0] = points[:,0].min() - .01
        model.links.append(Link(name=name,parent=root.name,xyz=position.tolist(),rpy=[0,0,math.pi]))
    model.name = 'car1_simulation_draft'
    model.import_notes.append('Simulation draft: wheel radius estimated from reduced CAD geometry; forward is CAD -X. Level test sensors sit 10 mm outside their CAD housings. Verify before real use.')
    model = Model.model_validate(model.model_dump())
    (out/'simulation.robot-builder.json').write_text(model.model_dump_json(),encoding='utf-8')
    (out/'car1-simulation-model.zip').write_bytes(bundle(model)[0])
    config = RobotConfiguration()
    config.drive.base_frame = root.name
    config.drive.left_joints = ['Wheel_3_joint','Wheel_4_joint']
    config.drive.right_joints = ['Wheel_2_joint','Wheel_joint']
    config.drive.wheel_radius = radius
    config.drive.lidar_frame = 'test_lidar_frame'
    config.drive.camera_frame = 'test_camera_frame'
    with patch.object(main,'init_rerun'), TestClient(main.app) as client:
        initial = checked(client.get('/api/robot/setup'))
        package = checked(client.post('/api/model-builder/setup',json=model.model_dump()))
        checked(client.post('/api/robot/setup/inspect',json=package))
        draft = {**package,'robot_config':config.model_dump(),'name':model.name,'target':'builtin','revision':initial['revision'],'positions':{}}
        checked(client.post('/api/robot/setup/preview',json=draft))
        checked(client.post('/api/robot/setup/apply',json=draft))
        saved = checked(client.post('/api/project/export',json={'name':model.name,'positions':{}}))
        assert saved['schema_version'] == 3
        assert saved['robot_assets'] == package['robot_assets']
        checked(client.post('/api/project/import',json=saved))
        assert checked(client.get('/api/robot/setup'))['robot_assets'] == package['robot_assets']
        (out/'car1-simulation.project.json').write_text(json.dumps(saved,separators=(',',':')),encoding='utf-8')
        world = generate_project(out/'webots',main.runtime.robot,config,12345,'car1-test')
        assert world.read_text().count('HingeJoint {') == 4
        received = {}
        handle = main.runtime.bus.subscribe('node/sim/out/truth',lambda message:received.update(message.payload))
        try:
            checked(client.post('/api/graph/start'))
            main.runtime.graph.update_node_params('drive',{'mode':'manual'})
            keyboard = main.runtime.graph.nodes['keyboard'].node_obj
            keyboard.acquire('car1-test')
            deadline = time.monotonic()+10
            sequence = 0
            while time.monotonic()<deadline and received.get('pose',[0])[0]<.1:
                keyboard.accept_keys('car1-test',sequence,['KeyW'])
                sequence += 1
                time.sleep(.1)
            keyboard.release('car1-test')
            assert received.get('pose',[0])[0] >= .1, received
            assert not [n for n in main.runtime.graph.to_dict()['nodes'] if n['error']]
            print('PASS car1 setup, save/reopen, embedded appearance, built-in drive, Webots generation',flush=True)
            print('Estimated radius:',radius,'Telemetry:',received,flush=True)
            (out/'simulation-result.json').write_text(json.dumps({'estimated_radius_m':radius,'telemetry':received,'webots':'generated, not launched'},indent=2),encoding='utf-8')
        finally:
            client.post('/api/graph/stop')
            handle.close()
        draft['target'] = 'webots'
        draft['revision'] = checked(client.get('/api/robot/setup'))['revision']
        checked(client.post('/api/robot/setup/apply',json=draft))
        saved = checked(client.post('/api/project/export',json={'name':model.name+'_webots','positions':{}}))
        (out/'car1-webots.project.json').write_text(json.dumps(saved,separators=(',',':')),encoding='utf-8')


if __name__ == '__main__':
    logging.disable(logging.INFO)
    main_test()
