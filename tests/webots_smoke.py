"""Optional real Webots test. Starts and closes only its own simulator process."""
import os
import argparse
import json
import socket
import sys
import time
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ports = []
for _ in range(2):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0)); ports.append(sock.getsockname()[1])
os.environ["PYROBOT_BUS_PUB"] = f"tcp://127.0.0.1:{ports[0]}"
os.environ["PYROBOT_BUS_SUB"] = f"tcp://127.0.0.1:{ports[1]}"

from core.runtime.session import Runtime
from core.runtime.project import ProjectDocument


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path)
    parser.add_argument('--mesh', action='store_true')
    parser.add_argument('--return-home', action='store_true')
    parser.add_argument('--planner', choices=['astar','dijkstra'], default='astar')
    parser.add_argument('--controller', choices=['proportional','fuzzy'], default='proportional')
    args = parser.parse_args()
    doc = ProjectDocument.model_validate_json((ROOT/"examples/four-wheel/webots.pyrobot.json").read_text())
    if args.project:
        doc = ProjectDocument.model_validate_json(args.project.read_text(encoding='utf-8'))
    if args.mesh:
        from core.urdf.builder import Model
        from core.urdf.assets import builder_package
        package=builder_package(Model.model_validate_json((ROOT/'examples/model-builder/four-wheel-rover.robot-builder.json').read_text()))
        doc=ProjectDocument.model_validate({**doc.model_dump(),**package,'schema_version':3})
        doc.robot_config.drive.wheel_radius=.12
    for node in doc.nodes:
        if node.node_id == "sim": node.params["minimize"] = True
        if node.node_id == "nav":
            node.params.update(planner=args.planner, controller=args.controller)
    print(f"Algorithms: {args.planner} / {args.controller}", flush=True)
    with Runtime() as runtime:
        runtime.load_project(doc)
        received = {}
        handle = runtime.bus.subscribe("node/", lambda m: received.__setitem__(m.topic, m.payload))
        runtime.graph.start()
        simulator = runtime.graph.nodes["sim"].node_obj
        print("Webots log:", simulator.directory/"webots.log", flush=True)
        def wait(predicate, seconds=30):
            deadline = time.monotonic()+seconds
            while not predicate():
                state = runtime.graph.to_dict()
                failed = [n for n in state["nodes"] if n["error"]]
                if failed: raise AssertionError(failed)
                if time.monotonic()>deadline: raise AssertionError("Timed out; " + str(received.get("node/nav/out/path",{})))
                time.sleep(.05)
        wait(lambda: "node/sim/out/camera" in received and "node/slam/out/state" in received, 90)
        truth = received["node/sim/out/truth"]
        scan = received["node/sim/out/sensors"]["scan"]
        print("Initial pose:", truth["pose"], "lidar rear/front:", scan["ranges"][0], scan["ranges"][180], flush=True)
        assert abs(scan["ranges"][180]-1.95)<.2, "Lidar forward axis is incorrect"
        keyboard = runtime.graph.nodes["keyboard"].node_obj
        runtime.graph.update_node_params("drive", {"mode":"manual"})
        keyboard.acquire("smoke")
        start = truth["pose"][:]
        for seq in range(20):
            keyboard.accept_keys("smoke", seq, ["KeyW"])
            time.sleep(.1)
        keyboard.release("smoke")
        time.sleep(1.)
        stopped = received["node/sim/out/truth"]["pose"][:]
        print("After keyboard drive:", stopped, flush=True)
        assert stopped[0] > start[0]+.15, "Positive motor commands did not drive forward"
        time.sleep(.5)
        assert math.dist(stopped[:2],received["node/sim/out/truth"]["pose"][:2]) < .03
        runtime.graph.update_node_params("nav", {"waypoints":[[.8,0],[.8,1]],"enabled":True})
        runtime.graph.update_node_params("drive", {"mode":"autonomous"})
        wait(lambda: received.get("node/nav/out/path",{}).get("status")=="mission_complete", 90)
        report = received["node/nav/out/path"]
        assert report["planner"] == args.planner and report["controller"] == args.controller
        truth = received["node/sim/out/truth"]
        print("Final pose:", truth["pose"], "contacts:", truth["collisions"], flush=True)
        assert math.dist(truth["pose"][:2],[.8,1]) < .4
        assert truth["collisions"] == 0
        if args.return_home:
            home = received['node/nav/out/path']['home_pose']
            runtime.graph.update_node_params('nav', {'return_home':True, 'enabled':True})
            wait(lambda: received.get('node/nav/out/path',{}).get('status')=='home_reached',90)
            truth=received['node/sim/out/truth']
            assert math.dist(truth['pose'][:2],home[:2]) < .4
            error=(truth['pose'][2]-home[2]+math.pi)%(2*math.pi)-math.pi
            assert abs(error)<.2
            assert truth['collisions']==0
            print('PASS return home:',truth['pose'],'home:',home,flush=True)
        result = dict(planner=args.planner, controller=args.controller,
                      project=str(args.project or "examples/four-wheel/webots.pyrobot.json"),
                      return_home=args.return_home, pose=truth['pose'], collisions=truth['collisions'],
                      status=received['node/nav/out/path']['status'])
        output = ROOT/'artifacts'/f'webots-{args.planner}-{args.controller}.json'
        output.write_text(json.dumps(result,indent=2),encoding='utf-8')
        runtime.graph.stop()
        handle.close()
        assert simulator._process.poll() is not None
        print("PASS: Webots lidar/camera, manual drive, release stop, two waypoints and process cleanup", flush=True)


if __name__ == "__main__":
    main()
