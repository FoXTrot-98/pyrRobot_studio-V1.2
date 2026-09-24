"""Optional extended Webots diagnostic: repeated turns and waypoint missions."""
import json
import math
import time
from collections import Counter
import numpy as np
from webots_smoke import ROOT, Runtime, ProjectDocument
from core.simulation.world import raycast, sensor_pose, wrap


def main():
    doc = ProjectDocument.model_validate_json((ROOT/'examples/four-wheel/webots.pyrobot.json').read_text())
    for node in doc.nodes:
        if node.node_id == 'sim': node.params['minimize'] = True
    latest, records, states, commands = {}, {}, [], []
    def receive(message):
        latest[message.topic] = message.payload
        if message.topic in ('node/sim/out/sensors', 'node/sim/out/truth', 'node/slam/out/state'):
            records.setdefault(message.payload['time'], {})[message.topic] = message.payload
        if message.topic == 'node/nav/out/path': states.append(message.payload['status'])
        if message.topic == 'node/drive/out/cmd_vel': commands.append((time.monotonic(), message.payload['linear'], message.payload['angular']))
    with Runtime() as runtime:
        runtime.load_project(doc)
        handle = runtime.bus.subscribe('node/', receive)
        runtime.graph.start()
        print('Log:', runtime.graph.nodes['sim'].node_obj.directory/'webots.log', flush=True)
        def wait(predicate, timeout=90):
            deadline = time.monotonic()+timeout
            while not predicate():
                assert runtime.graph._running, runtime.graph.failure_reason
                assert time.monotonic()<deadline, latest.get('node/nav/out/path', {}).get('status')
                time.sleep(.05)
        wait(lambda: 'node/slam/out/state' in latest)
        runtime.graph.update_node_params('drive', {'mode':'manual'})
        keyboard = runtime.graph.nodes['keyboard'].node_obj
        keyboard.acquire('mapping-test')
        seq = 0
        for keys, seconds in [([],1), (['KeyA'],12), ([],1), (['KeyD'],12), ([],1)]:
            until = time.monotonic()+seconds
            while time.monotonic()<until:
                keyboard.accept_keys('mapping-test',seq,keys); seq += 1
                time.sleep(.075)
            print('Phase', keys, 'truth', latest['node/sim/out/truth']['pose'], 'estimate', latest['node/slam/out/state']['pose'], flush=True)
        keyboard.release('mapping-test')
        try:
            runtime.graph.update_node_params('nav', {'waypoints':[[.8,0],[.8,2],[0,2],[0,0]], 'enabled':True})
            runtime.graph.update_node_params('drive', {'mode':'autonomous'})
            wait(lambda: latest.get('node/nav/out/path',{}).get('status')=='mission_complete',120)
        finally:
            runtime.graph.stop()
            handle.close()
            output=ROOT/'artifacts/webots-mapping-diagnostic.json'
            output.write_text(json.dumps({'records':records,'statuses':dict(Counter(states)), 'commands':commands}))
            errors=[]
            for record in records.values():
                truth=record.get('node/sim/out/truth'); state=record.get('node/slam/out/state'); sensors=record.get('node/sim/out/sensors')
                if truth and state:
                    errors.append((math.dist(truth['pose'][:2],state['pose'][:2]),abs(wrap(truth['pose'][2]-state['pose'][2]))))
                if truth and sensors and len(errors)==1:
                    scan=sensors['scan']
                    expected,_=raycast(sensor_pose(truth['pose'],scan['offset']),np.array(scan['angles']),obstacles=doc.robot_config.environment.boxes())
                    print('Scan range errors median/p90:', np.percentile(np.abs(expected-np.array(scan['ranges'])),[50,90]), flush=True)
            print('Pose error max (m,rad):',np.max(errors,axis=0),'statuses:',Counter(states), flush=True)
            print('Saved',output,flush=True)
        maximum = np.max(errors, axis=0)
        assert maximum[0] < .12 and maximum[1] < .06, f'Mapping drift: {maximum}'
        assert latest['node/sim/out/truth']['collisions'] == 0
        assert math.dist(latest['node/sim/out/truth']['pose'][:2],[0,0]) < .35
        assert latest['node/nav/out/path']['status'] == 'mission_complete'
        print('PASS: repeated turns, stable pose, four waypoints and no collisions',flush=True)


if __name__=='__main__': main()
