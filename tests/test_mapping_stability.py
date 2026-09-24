import math
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
from core.simulation.navigation import LidarSlam, WheelOdometry, follow_path
from core.simulation.world import FourWheelSimulator, wrap
from core.simulation.webots_controller import lidar_angles
from core.simulation.webots_project import overview_viewpoint
from plugins.user.astar_navigation import AStarNavigation


class MappingStabilityTests(unittest.TestCase):
    def test_overview_faces_room_with_upright_camera(self):
        bounds = [-2, -2, 10, 8]
        eye, rotation = overview_viewpoint(bounds)
        matrix, _ = cv2.Rodrigues(np.array(rotation[:3])*rotation[3])
        forward = np.array([4, 3, 0])-eye
        forward /= np.linalg.norm(forward)
        np.testing.assert_allclose(matrix[:, 0], forward, atol=1e-8)
        self.assertGreater(matrix[2, 2], 0)
        # Entire floor fits inside the initial 45-degree overview frustum.
        for x in (bounds[0], bounds[2]):
            for y in (bounds[1], bounds[3]):
                local = matrix.T @ (np.array([x, y, 0])-eye)
                self.assertGreater(local[0], 0)
                self.assertLess(abs(local[2])/local[0], math.tan(math.pi/8))

    def test_webots_beams_use_pixel_centres_without_duplicate_seam(self):
        angles = np.array(lidar_angles(360, 2*math.pi))
        self.assertAlmostEqual(angles[0], math.pi-math.pi/360)
        np.testing.assert_allclose(np.diff(angles), -2*math.pi/360)
        self.assertAlmostEqual(angles[-1], -angles[0])

    def test_repeated_circuits_reuse_anchors_and_limit_heading_drift(self):
        sim, odom, slam = FourWheelSimulator(), WheelOdometry(), LidarSlam()
        first_anchor = None
        for _ in range(4):
            for _ in range(4):
                for linear, angular, count in ((.3, 0, 30), (0, math.pi/4, 20)):
                    for _ in range(count):
                        sim.step(linear, angular, .1)
                        ticks = np.rint(sim.wheels*np.array([1.01,1.01,.995,.995])*4096/(2*np.pi))
                        pose, _ = slam.update(odom.update(ticks,.12,.62), sim.scan([.05,0,0]))
                        if first_anchor is None: first_anchor = slam.submaps[0][0]
        self.assertIs(slam.submaps[0][0], first_anchor)
        self.assertLess(math.dist(pose[:2], sim.pose[:2]), .03)
        self.assertLess(abs(wrap(pose[2]-sim.pose[2])), .01)
        self.assertLessEqual(len(slam.submaps), 64)

    def test_navigation_heartbeat_retains_sensor_watchdog(self):
        node = AStarNavigation(node_id='test', bus=Mock())
        node.emit = Mock()
        with patch.object(node,'start_worker'), patch('plugins.user.astar_navigation.time.monotonic',return_value=10):
            node.on_start()
            sim, slam = FourWheelSimulator(), LidarSlam()
            scan = sim.scan([.05,0,0]); slam.update([0,0,0],scan)
            node.process('state', slam.state(scan,1.))
        original = node._last_command.copy()
        node.emit.reset_mock()
        with patch('plugins.user.astar_navigation.time.monotonic',return_value=10.6): node.on_tick()
        node.emit.assert_called_once_with('cmd_vel',original)
        with patch('plugins.user.astar_navigation.time.monotonic',return_value=11.6): node.on_tick()
        self.assertEqual(node.emit.call_args.args[1]['status'],'sensor_timeout')
        self.assertEqual(node.emit.call_args_list[-2].args[1]['linear'],0.)
        node.emit.reset_mock()
        with patch('plugins.user.astar_navigation.time.monotonic',return_value=12): node.on_tick()
        node.emit.assert_not_called()

    def test_rear_mounted_lidar_stops_at_front_obstacle_across_seam(self):
        scan={'angles':[math.pi-.1,-math.pi+.1], 'ranges':[.1,9.], 'offset':[0,0,math.pi]}
        linear, _, status = follow_path([0,0,0],[[0,0],[1,0]],[1,0],scan)
        self.assertEqual(linear,0.)
        self.assertEqual(status,'obstacle_stop')


if __name__=='__main__': unittest.main()
