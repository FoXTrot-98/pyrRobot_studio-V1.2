# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

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
    parser.add_argument('--world', type=Path)
    parser.add_argument('--output', type=Path, help='Write this run report to a distinct JSON file')
    parser.add_argument('--spawn', type=float, nargs=3)
    parser.add_argument('--spawn-height', type=float)
    parser.add_argument('--explore-seconds', type=float, default=0, help='Simulation seconds before requesting return home')
    parser.add_argument('--finish-exploration', action='store_true',
                        help='Wait for exploration to choose return home itself (no operator return command).')
    parser.add_argument('--sensor-only', action='store_true')
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
    if args.world:
        from core.simulation.external_world import inspect
        info=inspect(args.world)
        doc.robot_config.webots_world=info['path']
        doc.robot_config.webots_world_hash=info['sha256']
        doc.robot_config.mapping.origin=[-15,-15]
        doc.robot_config.mapping.width=200
        doc.robot_config.mapping.height=200
        doc.robot_config.mapping.resolution=.15
    if args.spawn is not None:doc.robot_config.spawn_pose=args.spawn
    if args.spawn_height is not None:doc.robot_config.spawn_height=args.spawn_height
    doc=ProjectDocument.model_validate(doc.model_dump())
    for node in doc.nodes:
        if node.node_id == "sim": node.params["minimize"] = True
        if node.node_id == "nav":
            node.params.update(planner=args.planner, controller=args.controller)
    print(f"Algorithms: {args.planner} / {args.controller}", flush=True)
    with Runtime() as runtime:
        runtime.load_project(doc)
        received = {}
        navigation_failures = []
        exploration_travel = [0.]
        def observe(message):
            received[message.topic] = message.payload
            if message.topic == 'node/nav/out/path' and message.payload.get('status') in ('navigation_failed', 'stalled'):
                navigation_failures.append(message.payload)
            if message.topic == 'node/sim/out/truth':
                exploration_travel[0] = max(exploration_travel[0], math.dist(
                    doc.robot_config.spawn_pose[:2], message.payload['pose'][:2]))
        handle = runtime.bus.subscribe("node/", observe)
        runtime.graph.start()
        simulator = runtime.graph.nodes["sim"].node_obj
        print("Webots log:", simulator.directory/"webots.log", flush=True)
        def wait(predicate, seconds=30):
            deadline = time.monotonic()+seconds
            while not predicate():
                state = runtime.graph.to_dict()
                failed = [n for n in state["nodes"] if n["error"]]
                if failed: raise AssertionError(failed)
                if args.explore_seconds or args.finish_exploration:
                    if navigation_failures or time.monotonic()>deadline:
                        output = args.output.with_suffix('.failure.json') if args.output else ROOT/'artifacts'/'webots-exploration-failure.json'
                        output.parent.mkdir(parents=True,exist_ok=True)
                        output.write_text(json.dumps(dict(report=received.get('node/nav/out/path'),
                            state=received.get('node/slam/out/state'), truth=received.get('node/sim/out/truth'),
                            failures=navigation_failures),indent=2),encoding='utf-8')
                        raise AssertionError(f"Exploration failed; diagnostic: {output}; " + str(received.get('node/nav/out/path',{})))
                if time.monotonic()>deadline: raise AssertionError("Timed out; " + str(received.get("node/nav/out/path",{})))
                time.sleep(.05)
        wait(lambda: "node/sim/out/camera" in received and "node/slam/out/state" in received, 90)
        truth = received["node/sim/out/truth"]
        scan = received["node/sim/out/sensors"]["scan"]
        print("Initial pose:", truth["pose"], "lidar rear/front:", scan["ranges"][0], scan["ranges"][180], flush=True)
        if doc.robot_config.webots_world:
            assert truth['obstacles']==[]
            assert any(scan['hits']), 'External geometry was not sensed'
            pose=received['node/slam/out/state']['pose']
            assert math.dist(pose[:2],doc.robot_config.spawn_pose[:2])<.2, pose
            if args.sensor_only:
                # Exercise settling and sustained sensor delivery, not only the
                # first frame (which can precede spawn validation failures).
                first_time = truth['time']
                wait(lambda: received.get('node/sim/out/truth', {}).get('time', 0) >= first_time+3, 30)
                runtime.graph.stop();handle.close()
                assert simulator._process.poll() is not None
                print('PASS external world sensor data, spawn frame and process cleanup',flush=True)
                return
        else:
            assert abs(scan["ranges"][180]-1.95)<.2, "Lidar forward axis is incorrect"
        if args.explore_seconds or args.finish_exploration:
            runtime.graph.update_node_params('nav',{'explore':True,'enabled':True})
            runtime.graph.update_node_params('drive',{'mode':'autonomous'})
            if args.finish_exploration:
                wait(lambda: received.get('node/nav/out/path',{}).get('status')=='home_reached',120)
            else:
                end_time=truth['time']+args.explore_seconds
                wait(lambda: received['node/sim/out/truth']['time']>=end_time,max(90,args.explore_seconds*10))
            truth=received['node/sim/out/truth']
            assert exploration_travel[0]>.3, 'Exploration did not move'
            assert truth['collisions']==0
            print('Exploration pose:',truth['pose'],'status:',received['node/nav/out/path']['status'],flush=True)
            home=received['node/nav/out/path']['home_pose']
            if not args.finish_exploration:
                runtime.graph.update_node_params('nav',{'explore':False,'return_home':True,'enabled':True})
                wait(lambda: received.get('node/nav/out/path',{}).get('status')=='home_reached',90)
            truth=received['node/sim/out/truth']
            assert math.dist(truth['pose'][:2],home[:2])<.4, truth
            assert truth['collisions']==0
            assert not navigation_failures, navigation_failures
            heading_error=(truth['pose'][2]-home[2]+math.pi)%(2*math.pi)-math.pi
            assert abs(heading_error)<.2, truth
            result=dict(world=doc.robot_config.webots_world or 'generated-room',project=str(args.project),planner=args.planner,
                world_hash=doc.robot_config.webots_world_hash,spawn=doc.robot_config.spawn_pose,
                spawn_height=doc.robot_config.spawn_height,physics=doc.robot_config.physics.model_dump(),
                explore_seconds=args.explore_seconds,
                controller=args.controller,automatic_return=args.finish_exploration,
                max_displacement=exploration_travel[0],home=home,pose=truth['pose'],
                home_error=math.dist(truth['pose'][:2],home[:2]),heading_error=heading_error,
                collisions=truth['collisions'],report=received['node/nav/out/path'])
            output=args.output or ROOT/'artifacts'/'webots-exploration.json'
            output.parent.mkdir(parents=True,exist_ok=True)
            output.write_text(json.dumps(result,indent=2),encoding='utf-8')
            runtime.graph.stop();handle.close()
            assert simulator._process.poll() is not None
            print('PASS imported-world exploration and return home:',truth['pose'],flush=True)
            return
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
        forward = ((stopped[0]-start[0])*math.cos(start[2])+
                   (stopped[1]-start[1])*math.sin(start[2]))
        assert forward > .15, "Positive motor commands did not drive forward"
        time.sleep(.5)
        assert math.dist(stopped[:2],received["node/sim/out/truth"]["pose"][:2]) < .03
        # The same route relative to the spawn, including rotated/translated worlds.
        sx,sy,yaw=doc.robot_config.spawn_pose
        waypoints=[[sx+x*math.cos(yaw)-y*math.sin(yaw),
                    sy+x*math.sin(yaw)+y*math.cos(yaw)] for x,y in ((.8,0),(.8,1))]
        runtime.graph.update_node_params("nav", {"waypoints":waypoints,"enabled":True})
        runtime.graph.update_node_params("drive", {"mode":"autonomous"})
        wait(lambda: received.get("node/nav/out/path",{}).get("status")=="mission_complete", 90)
        report = received["node/nav/out/path"]
        assert report["planner"] == args.planner and report["controller"] == args.controller
        truth = received["node/sim/out/truth"]
        print("Final pose:", truth["pose"], "contacts:", truth["collisions"], flush=True)
        waypoint_error=math.dist(truth["pose"][:2],waypoints[-1])
        assert waypoint_error < .4
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
        estimate=received['node/slam/out/state']['pose']
        result = dict(planner=args.planner, controller=args.controller,
                      world=doc.robot_config.webots_world or 'generated-room',
                      world_hash=doc.robot_config.webots_world_hash,
                      physics=doc.robot_config.physics.model_dump(),spawn=doc.robot_config.spawn_pose,
                      forward_distance=forward,waypoints=waypoints,waypoint_error=waypoint_error,
                      estimated_pose=estimate,
                      localization_position_error=math.dist(estimate[:2],truth['pose'][:2]),
                      localization_heading_error=(estimate[2]-truth['pose'][2]+math.pi)%(2*math.pi)-math.pi,
                      home_error=math.dist(truth['pose'][:2],home[:2]) if args.return_home else None,
                      home_heading_error=error if args.return_home else None,
                      project=str(args.project or "examples/four-wheel/webots.pyrobot.json"),
                      return_home=args.return_home, pose=truth['pose'], collisions=truth['collisions'],
                      status=received['node/nav/out/path']['status'])
        output = args.output or ROOT/'artifacts'/f'webots-{args.planner}-{args.controller}.json'
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(result,indent=2),encoding='utf-8')
        runtime.graph.stop()
        handle.close()
        assert simulator._process.poll() is not None
        print("PASS: Webots lidar/camera, manual drive, release stop, two waypoints and process cleanup", flush=True)


if __name__ == "__main__":
    main()
