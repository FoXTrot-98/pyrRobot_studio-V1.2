# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

import math
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
from core.simulation.navigation import LidarSlam, WheelOdometry, follow_path
from core.simulation.world import FourWheelSimulator, wrap, advance, raycast, sensor_pose
from core.simulation.webots_controller import lidar_angles
from core.simulation.webots_project import overview_viewpoint
from plugins.user.astar_navigation import AStarNavigation


class MappingStabilityTests(unittest.TestCase):
    def test_gyro_keeps_circular_wall_map_aligned_when_scan_heading_is_ambiguous(self):
        slam = LidarSlam(origin=(-12,-12),size=(200,200))
        actual, odometry = np.zeros(3), np.zeros(3)
        angles = np.linspace(-math.pi,math.pi,360,endpoint=False)
        for frame in range(150):
            if frame:
                actual = advance(actual,.06,.04)
                odometry = advance(odometry,.0612,.04)
            mount = sensor_pose(actual,[.05,0,0])
            directions = np.column_stack([np.cos(angles+actual[2]),np.sin(angles+actual[2])])
            projection = directions @ mount[:2]
            ranges = -projection+np.sqrt(projection**2+100-np.dot(mount[:2],mount[:2]))
            scan = dict(ranges=np.minimum(ranges,9).tolist(),angles=angles.tolist(),
                        hits=(ranges<9).tolist(),offset=[.05,0,0])
            slam.update(odometry,scan,frame*.04)
            self.assertLess(abs(wrap(slam.pose[2]-actual[2])),1e-9)
            self.assertLess(math.dist(slam.pose[:2],actual[:2]),.09)
        occupied = slam.origin+(np.argwhere(slam.grid>.7)[:,::-1]+.5)*slam.resolution
        self.assertGreater(len(occupied),100)
        self.assertLess(np.percentile(np.abs(np.linalg.norm(occupied,axis=1)-10),95),.15)

    def test_integrated_gyro_preserves_heading_when_wheels_slip_and_lidar_sees_nothing(self):
        from plugins.user.wheel_odometry import EncoderOdometry
        from core.messages import validate_payload
        node = EncoderOdometry(node_id='odom',bus=Mock())
        node.emit = Mock()
        with patch.object(node,'start_worker'):
            node.on_start()
        slam = LidarSlam()
        slam.pose = np.array([4.,-3.,1.2])
        scan = dict(ranges=[9.]*360,angles=np.linspace(-math.pi,math.pi,360,endpoint=False).tolist(),
                    hits=[False]*360,offset=[.05,0,0],range_max=9.)
        for frame in range(50):
            # Accumulated gyro angles also survive dropped packets and wraps.
            wheel_angle = frame*.6*.62/(2*.12)
            ticks = np.rint(np.array([-1,-1,1,1])*wheel_angle*4096/(2*math.pi)).astype(int).tolist()
            packet = validate_payload('pyrobot/SensorPacket@1',dict(ticks=ticks,wheel_radius=.12,track=.62,
                         ticks_per_turn=4096,gyro_yaw=frame*.18,scan=scan,time=frame*.6))
            node.process('sensors',packet)
            observation = node.emit.call_args.args[1]
            slam.update(observation['odometry'],observation['scan'],observation['gyro_yaw'])
            self.assertLess(abs(wrap(slam.pose[2]-(1.2+frame*.18))),1e-9)
            np.testing.assert_allclose(slam.pose[:2],[4,-3],atol=1e-9)
        # Old/hardware packets without a gyro keep encoder-only behavior.
        encoder_only = WheelOdometry()
        encoder_only.update([0]*4,.12,.62,4096)
        legacy = encoder_only.update(ticks,.12,.62,4096)
        self.assertGreater(abs(wrap(legacy[2]-observation['odometry'][2])),.1)

    def test_skipped_scans_and_skid_steer_turns_keep_walls_stationary(self):
        from core.simulation.world import OBSTACLES
        slam, actual, odometry = LidarSlam(), np.zeros(3), np.zeros(3)
        angles = np.linspace(-math.pi, math.pi, 360, endpoint=False)
        for frame in range(70):
            if frame:
                # 0.6 s gaps with wheel slip: encoders turn 0.6 rad while the
                # physical chassis turns only 0.18 rad. A fixed 7*0.03 rad
                # ICP correction budget cannot catch up to that discrepancy.
                direction = 1 if frame < 35 else -1
                actual = advance(actual, .018, direction*.18)
                odometry = advance(odometry, .018, direction*.6)
            ranges, hits = raycast(sensor_pose(actual, [.05,0,0]), angles)
            scan = dict(ranges=ranges.tolist(), angles=angles.tolist(),
                        hits=(hits >= 0).tolist(), offset=[.05,0,0])
            slam.update(odometry, scan)
            self.assertLess(math.dist(slam.pose[:2],actual[:2]), .04)
            self.assertLess(abs(wrap(slam.pose[2]-actual[2])), .02)
        occupied = slam.origin + (np.argwhere(slam.grid > .7)[:,::-1]+.5)*slam.resolution
        distances = []
        for a,b,c,d,_ in OBSTACLES:
            outside = np.maximum(np.maximum([a,b]-occupied,occupied-[c,d]),0.)
            distance = np.linalg.norm(outside,axis=1)
            inside = np.all(outside == 0,axis=1)
            distance[inside] = np.min(np.abs(occupied[inside][:,[0,1,0,1]]-[a,b,c,d]),axis=1)
            distances.append(distance)
        self.assertGreater(len(occupied),20)
        self.assertLess(np.percentile(np.min(distances,axis=0),95), .12)

    def test_single_wall_does_not_invent_motion_in_unobservable_direction(self):
        # Real Webots range noise perturbs wall normals. With exact encoders,
        # the old damped ICP still drifted 1.24 m along this wall in 20 seconds.
        rng = np.random.default_rng(9)
        slam, pose = LidarSlam(), np.zeros(3)
        angles = np.linspace(-math.pi, math.pi, 360, endpoint=False)
        for _ in range(200):
            pose = advance(pose, .01, .005)
            ranges, hits = raycast(sensor_pose(pose, [.05, 0, 0]), angles,
                                   obstacles=[[3, -50, 3.2, 50, 1]])
            scan = dict(ranges=np.clip(ranges+rng.normal(0, .0045, 360), .05, 9).tolist(),
                        angles=angles.tolist(), hits=(hits >= 0).tolist(), offset=[.05, 0, 0])
            slam.update(pose, scan)
        self.assertLess(math.dist(slam.pose[:2], pose[:2]), .03)
        self.assertLess(abs(wrap(slam.pose[2]-pose[2])), .01)
        occupied = slam.origin + (np.argwhere(slam.grid > .7)[:, ::-1]+.5)*slam.resolution
        self.assertGreater(len(occupied), 20)
        self.assertLess(np.percentile(np.abs(occupied[:, 0]-3), 95), .12)

    def test_estimate_box_uses_robot_geometry_and_only_actual_lidar_hits_are_drawn(self):
        from core.urdf.model import load_urdf, Origin
        from plugins.user.simulation_view import SimulationRerunView
        model=load_urdf(Path(__file__).resolve().parents[1]/'examples/four-wheel/robot.urdf')
        # Keep the existing drive/sensors but change the fixed body dimensions.
        for name,link in model.links.items():
            if name!='base_link' and model.static_transform('base_link',name) is not None:
                link.visual_geometry={}
        model.links['base_link'].visual_geometry={'type':'box','size':'.4 .3 .2'}
        model.links['base_link'].visual_origin=Origin(xyz=(.1,0,.3))
        node=SimulationRerunView(node_id='view',bus=Mock());node.robot_model=model
        with patch.object(node,'start_worker'), patch('plugins.user.simulation_view.rr.log') as log, patch('plugins.user.simulation_view.rr.send_blueprint'), patch('plugins.user.simulation_view.rr.set_time'):
            node.on_start()
            log.reset_mock()
            node.process('state',{'pose':[2,3,math.pi/2],'time':1.,'scan':{'offset':[0,0,0],'angles':[0,math.pi/2],'ranges':[1,9],'hits':[True,False]}})
            entries={call.args[0]:call.args[1] for call in log.call_args_list}
            box=entries['simulation/estimated_pose']
            np.testing.assert_allclose(box.centers.as_arrow_array().to_pylist(),[[2,3.1,.3]],atol=1e-6)
            np.testing.assert_allclose(box.half_sizes.as_arrow_array().to_pylist(),[[.2,.15,.1]],atol=1e-6)
            hits=entries['simulation/lidar_hits'].positions.as_arrow_array().to_pylist()
            self.assertEqual(len(hits),1)
            np.testing.assert_allclose(hits[0][:2],[2,4],atol=1e-6)

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
        # Establish a sensor baseline before the first commanded movement.
        odom.update([0]*4,sim.radius,sim.track)
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
