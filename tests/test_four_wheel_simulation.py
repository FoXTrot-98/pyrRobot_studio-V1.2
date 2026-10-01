# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

import math
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import rerun as rr

from core.urdf.model import load_urdf, parse_urdf
from core.simulation.world import FourWheelSimulator, raycast, robot_dimensions, camera_image, collision
from core.simulation.navigation import WheelOdometry, LidarSlam, plan_path, follow_path
from core.runtime.project import ProjectDocument
from core.runtime.session import Runtime
from plugins.user.astar_navigation import AStarNavigation

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/four-wheel"


class SimulationTests(unittest.TestCase):
    def test_navigation_watchdog_pause_and_fresh_sensor_recovery(self):
        node = AStarNavigation(node_id="watchdog", bus=Mock())
        node.emit = Mock()
        with patch.object(node, "start_worker"), patch("plugins.user.astar_navigation.time.monotonic", return_value=10):
            node.on_start()
        # The idle hook must stop even before the first observation exists.
        with patch("plugins.user.astar_navigation.time.monotonic", return_value=12):
            node.on_tick()
        self.assertEqual(node.emit.call_args.args[1]["status"], "sensor_timeout")
        self.assertIsNone(node.emit.call_args.args[1]["distance_to_goal"])
        sim, slam = FourWheelSimulator(), LidarSlam()
        scan = sim.scan([.05, 0, 0])
        slam.update([0, 0, 0], scan)
        observation = slam.state(scan, 1.0)
        with patch("plugins.user.astar_navigation.time.monotonic", return_value=13):
            node.process("state", observation)
        self.assertFalse(node._timed_out)
        node.emit.reset_mock()
        with patch("plugins.user.astar_navigation.time.monotonic", return_value=15):
            node.process("state", observation)  # Replay cannot refresh the watchdog.
            node.process("state", dict(observation, time=.5))
            node.on_tick()
        self.assertEqual(node.emit.call_args_list[0].args[1]["linear"], 0)
        self.assertEqual(node.emit.call_args.args[1]["status"], "sensor_timeout")
        node.params["enabled"] = False
        node.on_params_changed({"enabled": False})
        self.assertEqual(node.emit.call_args.args[1]["status"], "paused")
        node.params["enabled"] = True
        with patch("plugins.user.astar_navigation.time.monotonic", return_value=16):
            node.process("state", dict(observation, time=2.0))
        self.assertFalse(node._timed_out)
        self.assertNotEqual(node.emit.call_args.args[1]["status"], "sensor_timeout")

    def test_urdf_contains_four_wheels_and_fixed_sensor_frames(self):
        model = load_urdf(EXAMPLE / "robot.urdf")
        self.assertEqual(sum(j.joint_type == "continuous" for j in model.joints.values()), 4)
        radius, track, mounts = robot_dimensions(model)
        self.assertAlmostEqual(radius, .12)
        self.assertAlmostEqual(track, .62)
        self.assertAlmostEqual(mounts["lidar_link_height"], .44)
        self.assertIn("camera_optical_frame", model.links)

    def test_static_transform_composition_and_inverse(self):
        model = parse_urdf('''<robot name="test"><link name="a"/><link name="b"/><link name="c"/>
          <joint name="ab" type="fixed"><parent link="a"/><child link="b"/><origin xyz="1 0 0" rpy="0 0 1.5707963267948966"/></joint>
          <joint name="bc" type="fixed"><parent link="b"/><child link="c"/><origin xyz="1 0 0"/></joint></robot>''')
        forward = np.array(model.static_transform("a","c")["matrix"])
        inverse = np.array(model.static_transform("c","a")["matrix"])
        np.testing.assert_allclose(forward[:3,3],[1,1,0],atol=1e-8)
        np.testing.assert_allclose(forward @ inverse,np.eye(4),atol=1e-8)

    def test_lidar_measures_world_and_camera_changes_with_pose(self):
        ranges,_ = raycast(np.zeros(3),np.array([0, math.pi/2, math.pi]))
        np.testing.assert_allclose(ranges, [2,5,2], atol=1e-8)
        self.assertFalse(np.array_equal(camera_image([0,0,0]),camera_image([0,0,1])))
        self.assertTrue(collision(np.array([2.1,0,0])))

    def test_planner_routes_around_obstacles_and_rejects_blocked_goal(self):
        grid = np.zeros((40,40),dtype=int)
        grid[5:30,18:21] = 100
        path = plan_path(grid,[0,0],.1,[.5,1.5],[3.5,1.5],radius=.15)
        self.assertTrue(path)
        self.assertTrue(any(p[1] > 3 or p[1] < .5 for p in path))
        self.assertFalse(plan_path(grid,[0,0],.1,[.5,1.5],[1.9,1.5],radius=.15))

    def test_closed_loop_reaches_goal_from_sensors_only(self):
        sim, odometry, slam = FourWheelSimulator(), WheelOdometry(), LidarSlam()
        path, command, goal = [], (0,0), [8,6]
        reached = False
        for frame in range(650):
            sim.step(*command,.1)
            ticks = np.rint(sim.wheels*np.array([1.01,1.01,.995,.995])*4096/(2*np.pi))
            odom = odometry.update(ticks,.12,.62)
            scan = sim.scan([.05,0,0])
            pose,_ = slam.update(odom,scan)
            if frame % 10 == 0 or not path:
                state = slam.state(scan,sim.time)
                path = plan_path(state["grid"],state["origin"],state["resolution"],pose,goal)
            linear,angular,status = follow_path(pose,path,goal,scan)
            command = linear,angular
            if status == "goal_reached":
                reached = True
                break
        self.assertTrue(reached, f"Did not reach goal; pose={pose}")
        self.assertEqual(sim.collisions,0)
        self.assertLess(math.dist(sim.pose[:2],goal),.35)
        self.assertLess(math.dist(sim.pose[:2],pose[:2]),.15)
        self.assertLess(math.dist(sim.pose[:2],pose[:2]),math.dist(sim.pose[:2],odom[:2]))
        print(f"Goal reached at {sim.time:.1f}s; collisions={sim.collisions}; SLAM error={math.dist(sim.pose[:2],pose[:2]):.3f}m")

    def test_project_runs_over_real_bus_with_strict_rerun(self):
        rr.init("four-wheel-test",spawn=False,strict=True)
        recording = rr.memory_recording()
        with Runtime() as runtime:
            document = ProjectDocument.model_validate_json((EXAMPLE/"navigation.pyrobot.json").read_text())
            runtime.load_project(document)
            received = {}
            handle = runtime.bus.subscribe("node/",lambda msg: received.__setitem__(msg.topic,msg.payload))
            runtime.graph.start()
            deadline = time.monotonic()+5
            while time.monotonic()<deadline:
                time.sleep(.1)
                if "node/nav/out/path" in received and "node/sim/out/camera" in received and received.get("node/sim/out/truth",{}).get("time",0)>1.5:
                    break
            self.assertIn("node/nav/out/path",received)
            self.assertIn("node/sim/out/camera",received)
            self.assertEqual(received["node/sim/out/truth"]["collisions"],0)
            runtime.graph.update_node_params("nav",{"enabled":False})
            time.sleep(.3)
            self.assertEqual(received["node/nav/out/cmd_vel"]["linear"],0)
            runtime.graph.update_node_params("nav", {"enabled": True})
            runtime.graph.nodes["encoders"].node_obj.stop()
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                if received["node/nav/out/path"]["status"] == "sensor_timeout":
                    break
                time.sleep(.05)
            self.assertEqual(received["node/nav/out/path"]["status"], "sensor_timeout")
            self.assertEqual(received["node/nav/out/cmd_vel"]["linear"], 0)
            self.assertEqual(received["node/nav/out/cmd_vel"]["angular"], 0)
            time.sleep(.3)
            stopped_pose = received["node/sim/out/truth"]["pose"]
            time.sleep(.3)
            np.testing.assert_allclose(received["node/sim/out/truth"]["pose"], stopped_pose)
            runtime.graph.stop()
            handle.close()
            self.assertTrue(all(n["error"] is None for n in runtime.graph.to_dict()["nodes"]))
        self.assertGreater(recording.num_msgs(),0)


if __name__ == "__main__":
    unittest.main()
