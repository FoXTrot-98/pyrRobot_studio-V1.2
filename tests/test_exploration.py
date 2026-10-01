# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Frontier reachability, mission bounds and pause behavior."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import unittest
import numpy as np
from unittest.mock import patch
from core.simulation.exploration import frontier_goal, exploration_path
import test_return_home

class ExplorationTests(unittest.TestCase):
    node = test_return_home.HomeTests.node
    send = test_return_home.HomeTests.send
    change = test_return_home.HomeTests.change
    stopped = test_return_home.HomeTests.stopped
    def test_sensor_driven_exploration_returns_home(self):
        from core.simulation.world import FourWheelSimulator
        from core.simulation.navigation import WheelOdometry, LidarSlam
        sim, odometry, slam = FourWheelSimulator(), WheelOdometry(), LidarSlam()
        node = self.node(explore=True, exploration_targets=20)
        command = (0.,0.)
        first_mapped = None
        for frame in range(2000):
            sim.step(*command,.1)
            ticks = np.rint(sim.wheels*4096/(2*np.pi))
            odom = odometry.update(ticks,.12,.62)
            scan = sim.scan([.05,0,0])
            slam.update(odom,scan)
            state = slam.state(scan,sim.time)
            if first_mapped is None: first_mapped=state['mapped_cells']
            with patch('plugins.user.astar_navigation.time.monotonic',return_value=sim.time):
                node.process('state',state)
            report=node.emit.call_args.args[1]
            cmd=[c.args[1] for c in node.emit.call_args_list if c.args[0]=='cmd_vel'][-1]
            command=cmd['linear'],cmd['angular']
            node.emit.reset_mock()
            if report['status'] in ('home_reached','navigation_failed','stalled'):break
        self.assertEqual(report['status'],'home_reached',report)
        self.assertGreaterEqual(report['exploration_targets'],3)
        self.assertGreater(state['mapped_cells'],first_mapped)
        self.assertEqual(sim.collisions,0)
        self.assertLess(np.linalg.norm(sim.pose[:2]),.4)

    def test_frontiers_and_known_routes(self):
        grid=np.full((30,30),-1)
        grid[5:25,5:25]=0
        goal=frontier_goal(grid,[0,0],.2,[3,3,0],.4)
        self.assertIsNotNone(goal)
        path=exploration_path({'grid':grid,'origin':[0,0],'resolution':.2},[3,3,0],goal,.4)
        self.assertTrue(path)
        for x,y in path:
            self.assertEqual(grid[int(y/.2),int(x/.2)],0)
        grid[5:25,5:25]=100
        grid[15,15]=0
        self.assertIsNone(frontier_goal(grid,[0,0],.2,[3.1,3.1,0],.4))

    def test_known_space_route_recovers_clear_continuous_start(self):
        grid = np.zeros((20,20),dtype=int)
        grid[5,5] = 100
        payload = {'grid':grid,'origin':[0.,0.],'resolution':.1}
        path = exploration_path(payload,[.899,.55,0.],[1.5,.55],.32)
        self.assertTrue(path)
        self.assertEqual(path[0],[.899,.55])
        self.assertFalse(exploration_path(payload,[.85,.55,0.],[1.5,.55],.32))
        grid[:,12] = -1
        self.assertFalse(exploration_path(payload,[.899,.55,0.],[1.5,.55],.32))

    def test_limit_return_pause_and_restart(self):
        node=self.node(explore=True,exploration_targets=1)
        with patch('plugins.user.astar_navigation.frontier_goal',return_value=[1.,0.]):
            result=self.send(node,1.,[0.,0.,0.])
        self.assertTrue(result['exploring'])
        self.assertEqual(result['exploration_targets'],1)
        self.change(node,enabled=False)
        self.assertEqual(self.send(node,2.,[1.,0.,0.])['status'],'paused')
        self.assertFalse(node._exploration_return)
        self.change(node,enabled=True)
        result=self.send(node,3.,[1.,0.,0.])
        self.assertEqual(result['status'],'returning_home')
        self.assertEqual(result['reason'],'Target limit reached')
        self.assertEqual(self.send(node,4.,[0.,0.,0.])['status'],'home_reached')
        self.stopped(node)
        self.change(node,explore=False,return_home=False)
        self.assertEqual(self.send(node,5.,[0.,0.,0.])['status'],'navigating')

    def test_blocked_frontier_is_skipped_but_failed_home_latches(self):
        node=self.node(explore=True,exploration_targets=1,blocked_timeout=1.)
        with patch('plugins.user.astar_navigation.frontier_goal',return_value=[1.,0.]):
            self.send(node,1.,[0.,0.,0.],blocked=True)
        result=self.send(node,2.,[0.,0.,0.],blocked=True)
        self.assertEqual(result['status'],'replanning')
        self.stopped(node)
        result=self.send(node,3.,[.5,0.,0.],blocked=True)
        self.assertTrue(result['returning_home'])
        self.assertEqual(result['status'],'no_path')
        result=self.send(node,4.,[.5,0.,0.],blocked=True)
        self.assertEqual(result['status'],'navigation_failed')
        self.assertEqual(self.send(node,5.,[.5,0.,0.])['status'],'navigation_failed')
        self.stopped(node)

    def test_no_frontiers_returns_home_without_claiming_full_map(self):
        node=self.node(explore=True)
        result=self.send(node,1.,[0.,0.,0.])
        self.assertEqual(result['status'],'home_reached')
        self.assertEqual(result['reason'],'No remaining reachable frontiers')
        self.stopped(node)

    def test_blocked_start_does_not_claim_exploration_finished(self):
        node = self.node(explore=True)
        result = self.send(node,1.,[0.,0.,0.],blocked=True)
        self.assertEqual(result['status'],'navigation_failed')
        self.assertFalse(result['returning_home'])
        self.assertIn('Robot',result['reason'])
        self.stopped(node)

    def test_newly_obstructed_frontier_is_skipped_immediately(self):
        node = self.node(explore=True)
        with patch('plugins.user.astar_navigation.frontier_goal',return_value=[1.,0.]):
            self.send(node,1.,[0.,0.,0.])
        with patch('plugins.user.astar_navigation.exploration_path',return_value=[]), patch(
                'plugins.user.astar_navigation.no_path_reason',return_value='Goal is inside the configured obstacle clearance.'):
            result = self.send(node,2.,[0.,0.,0.])
        self.assertEqual(result['status'],'replanning')
        self.assertIsNone(node._frontier)
        self.stopped(node)

if __name__=='__main__':unittest.main()
