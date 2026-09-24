"""Optional real Webots test. Starts and closes only its own simulator process."""
import os
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
    doc = ProjectDocument.model_validate_json((ROOT/"examples/four-wheel/webots.pyrobot.json").read_text())
    for node in doc.nodes:
        if node.node_id == "sim": node.params["minimize"] = True
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
        truth = received["node/sim/out/truth"]
        print("Final pose:", truth["pose"], "contacts:", truth["collisions"], flush=True)
        assert math.dist(truth["pose"][:2],[.8,1]) < .4
        assert truth["collisions"] == 0
        runtime.graph.stop()
        handle.close()
        assert simulator._process.poll() is not None
        print("PASS: Webots lidar/camera, manual drive, release stop, two waypoints and process cleanup", flush=True)


if __name__ == "__main__":
    main()
