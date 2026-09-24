"""Optional real native-model test; first use downloads official Webots assets."""
import sys
import time
import math
from webots_smoke import Runtime, ProjectDocument
from core.simulation.webots_examples import example_project


def run(profile):
    document=ProjectDocument.model_validate(example_project(profile))
    document.nodes[0].params['minimize']=True
    latest={}
    with Runtime() as runtime:
        runtime.load_project(document)
        handle=runtime.bus.subscribe('node/robot/out/',lambda msg:latest.__setitem__(msg.topic,msg.payload))
        runtime.graph.start(); node=runtime.graph.nodes['robot'].node_obj
        print(profile,'log:',node.directory/'webots.log',flush=True)
        def wait(predicate,seconds=180):
            deadline=time.monotonic()+seconds
            while not predicate():
                assert runtime.graph._running,runtime.graph.failure_reason
                assert time.monotonic()<deadline,latest.get('node/robot/out/state')
                time.sleep(.1)
        wait(lambda:'node/robot/out/state' in latest)
        state=latest['node/robot/out/state']
        print(profile,'devices:',[(j['name'],round(j['position'],3)) for j in state['joints']],flush=True)
        joint={'panda':'panda_joint2','nao':'RShoulderPitch','youbot':'arm2'}[profile]
        def position():return next(j['position'] for j in latest['node/robot/out/state']['joints'] if j['name']==joint)
        before=position()
        action={'panda':'reach_near','nao':'wave','youbot':'arm_home'}[profile]
        runtime.graph.update_node_params('robot',{'action':action})
        wait(lambda:latest['node/robot/out/state']['status']==action,30)
        wait(lambda:abs(position()-before)>.1,30)
        assert not latest['node/robot/out/state']['error'], latest['node/robot/out/state']
        if profile=='nao': wait(lambda:'node/robot/out/camera' in latest,30)
        runtime.graph.update_node_params('robot',{'action':'hold'})
        wait(lambda:latest['node/robot/out/state']['status']=='holding',30)
        if profile=='youbot':
            keyboard=runtime.graph.nodes['keyboard'].node_obj; keyboard.acquire('test')
            start=latest['node/robot/out/state']['position']
            for sequence in range(20): keyboard.accept_keys('test',sequence,['KeyS']); time.sleep(.1)
            keyboard.release('test'); time.sleep(.5)
            stopped=latest['node/robot/out/state']['position']
            assert math.dist(start[:2],stopped[:2])>.05
            time.sleep(.5)
            assert math.dist(stopped[:2],latest['node/robot/out/state']['position'][:2])<.03
        runtime.graph.stop(); handle.close()
        assert node._process.poll() is not None
        print('PASS',profile,'real joints, Studio action, hold, telemetry and cleanup',flush=True)


if __name__=='__main__':
    for profile in (sys.argv[1:] or ['panda','nao','youbot']):run(profile)
