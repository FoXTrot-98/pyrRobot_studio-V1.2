# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Algorithm invariants and sensor-driven comparisons on the same scenario."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
import itertools
import math
import time
import unittest
import numpy as np
from core.simulation.navigation import plan_path, follow_path, fuzzy_command, no_path_reason, WheelOdometry, LidarSlam
from core.simulation.world import FourWheelSimulator
import test_return_home

class AlgorithmTests(unittest.TestCase):
    def test_planners_match_cost_and_reject_corner_cutting(self):
        grid=np.zeros((30,30),dtype=int)
        grid[3:24,14:16]=100
        paths=[plan_path(grid,[0,0],.2,[1,2],[5,2],radius=.2,algorithm=a) for a in ('astar','dijkstra')]
        costs=[sum(math.dist(a,b) for a,b in zip(p,p[1:])) for p in paths]
        self.assertTrue(all(paths))
        self.assertAlmostEqual(*costs)
        for algorithm in ('astar','dijkstra'):
            self.assertEqual(plan_path([[0,100],[100,0]],[0,0],1,[.5,.5],[1.5,1.5],radius=0,algorithm=algorithm),[])
            self.assertEqual(plan_path(grid,[0,0],.2,[1,2],[2.9,2],algorithm=algorithm),[])

    def test_actual_pose_connection_preserves_clearance(self):
        grid=np.zeros((20,20),dtype=int)
        grid[5,5]=100
        origin=[0.,0.]
        # Start cell centre x=.85 is .30 from obstacle centre x=.55;
        # actual pose x=.899 is .349 away and may connect outward at radius .32.
        for algorithm in ('astar','dijkstra'):
            path=plan_path(grid,origin,.1,[.899,.55],[1.5,.55],radius=.32,algorithm=algorithm)
            self.assertTrue(path)
            self.assertEqual(path[0],[.899,.55])
            for a,b in zip(path,path[1:]):
                for t in np.linspace(0,1,25):
                    self.assertGreaterEqual(math.dist(np.asarray(a)*(1-t)+np.asarray(b)*t,[.55,.55]),.32-1e-9)
            self.assertFalse(plan_path(grid,origin,.1,[.85,.55],[1.5,.55],radius=.32,algorithm=algorithm))
            self.assertFalse(plan_path(grid,origin,.1,[.55,.55],[1.5,.55],radius=.32,algorithm=algorithm))
            self.assertFalse(plan_path(grid,origin,.1,[1.5,.55],[.85,.55],radius=.32,algorithm=algorithm))

    def test_no_path_diagnostics(self):
        grid=np.zeros((20,20),dtype=int)
        grid[5,5]=100
        self.assertIn("Robot is inside",no_path_reason(grid,[0,0],.1,[.85,.55,0],[1.5,.55],.32))
        self.assertIn("Goal is inside",no_path_reason(grid,[0,0],.1,[1.5,.55,0],[.85,.55],.32))
        self.assertIn("overlaps",no_path_reason(grid,[0,0],.1,[.55,.55,0],[1.5,.55],.32))
        self.assertIn("outside",no_path_reason(grid,[0,0],.1,[-1,0,0],[1.5,.55],.32))

    def test_follower_does_not_cut_inflated_corner(self):
        grid = np.zeros((20,20),dtype=int)
        grid[9,9] = 100
        state = {'grid':grid,'origin':[0.,0.],'resolution':.1}
        scan = {'angles':[0.], 'ranges':[9.], 'offset':[0.,0.,0.]}
        path = [[.5,.5],[1.,.5],[1.5,.5],[1.5,1.],[1.5,1.5]]
        linear,angular,status = follow_path([.5,.5,0.],path,path[-1],scan,map_state=state,radius=.4)
        self.assertEqual(status,'navigating')
        self.assertGreater(linear,0.)
        self.assertAlmostEqual(angular,0.)  # Follow the bend instead of cutting diagonally.

    def test_follower_limits_motion_before_newly_mapped_obstacle(self):
        grid = np.zeros((30,30),dtype=int)
        grid[10,14] = 100
        state = {'grid':grid,'origin':[-1.,-1.],'resolution':.1}
        scan = {'angles':[0.], 'ranges':[9.], 'offset':[0.,0.,0.]}
        linear,angular,_ = follow_path([0.,0.,0.],[[0.,0.],[1.,0.]],[1.,0.],scan,map_state=state,radius=.3)
        self.assertLess(linear,.65)
        self.assertEqual(angular,0.)
        self.assertGreaterEqual(math.dist([linear*.4,0.],[.45,.05]),.3)

    def test_corner_clearance_does_not_depend_on_instantaneous_turn_response(self):
        # A valid arc can be unsafe when a skid-steer drive has not yet turned.
        grid = np.zeros((12,12),dtype=int)
        grid[1,1] = 100
        state = {'grid':grid,'origin':[0.,0.],'resolution':.15}
        scan = {'angles':[0.], 'ranges':[9.], 'offset':[0.,0.,0.]}
        pose = [.709,.76884,3.01829]
        path = [[.975,.675],[.825,.675],[.675,.675],[.525,.825],
                [.375,.825],[.225,.825],[.075,.975]]
        for controller in ('proportional','fuzzy'):
            linear, angular, status = follow_path(pose,path,path[-1],scan,
                map_state=state,radius=.65,controller=controller)
            self.assertEqual(status,'navigating')
            self.assertLess(angular,0.)
            # Check the complete short motion for missing, partial and full yaw
            # response rather than assuming the command is physically achieved.
            for response in (0., .25, .5, 1.):
                rate = angular*response
                for t in np.linspace(0.,.4,41):
                    if rate == 0:
                        point = [pose[0]+linear*t*math.cos(pose[2]),pose[1]+linear*t*math.sin(pose[2])]
                    else:
                        point = [pose[0]+linear/rate*(math.sin(pose[2]+rate*t)-math.sin(pose[2])),
                                 pose[1]+linear/rate*(math.cos(pose[2])-math.cos(pose[2]+rate*t))]
                    self.assertGreaterEqual(math.dist(point,[.225,.225]),.65)

    def test_fuzzy_symmetry_bounds_and_hard_stop(self):
        for error in np.linspace(0,math.pi,40):
            left=fuzzy_command(error,2.,.65,.55)
            right=fuzzy_command(-error,2.,.65,.55)
            self.assertAlmostEqual(left[0],right[0])
            self.assertAlmostEqual(left[1],-right[1])
            self.assertTrue(0 <= left[0] <= .65)
            self.assertLessEqual(abs(left[1]),1.3)
        self.assertLess(fuzzy_command(0,.7,.65,.55)[0],fuzzy_command(0,2,.65,.55)[0])
        scan={'angles':[0.], 'ranges':[.3], 'offset':[0,0,0]}
        for controller in ('proportional','fuzzy'):
            self.assertEqual(follow_path([0,0,0],[[0,0],[1,0]],[2,0],scan,controller=controller),(0.,0.,'obstacle_stop'))
            self.assertEqual(follow_path([0,0,0],[],[2,0],scan,controller=controller)[2],'no_path')

    def test_live_switch_preserves_mission_and_failure_latch(self):
        helper=test_return_home.HomeTests()
        node=helper.node(blocked_timeout=1.)
        first=helper.send(node,1.,[0.,0.,0.])
        helper.change(node,planner="dijkstra",controller="fuzzy")
        helper.stopped(node)
        self.assertIsNone(node._last_command)
        report=helper.send(node,2.,[0.,0.,0.])
        self.assertEqual(report['mission_id'],first['mission_id'])
        self.assertEqual((report['planner'],report['controller']),("dijkstra","fuzzy"))
        helper.send(node,3.,[0.,0.,0.],True)
        helper.send(node,4.,[0.,0.,0.],True)
        helper.change(node,planner="astar")
        self.assertEqual(helper.send(node,5.,[0.,0.,0.])['mission_state'],'failed')
        helper.stopped(node)
        with self.assertRaises(ValueError):
            helper.node(planner="invalid").validate_configuration()

    def test_sensor_driven_comparison(self):
        results=[]
        for planner,controller,goal in itertools.product(("astar","dijkstra"),("proportional","fuzzy"),([.8,1.],[8.,6.])):
            sim,odom,slam=FourWheelSimulator(),WheelOdometry(),LidarSlam()
            command=(0.,0.)
            path=[]
            distance=0.
            started=time.perf_counter()
            blocked_frames=0
            for frame in range(650):
                before=sim.pose.copy()
                sim.step(*command,.1)
                distance+=math.dist(before[:2],sim.pose[:2])
                ticks=np.rint(sim.wheels*4096/(2*np.pi))
                estimate=odom.update(ticks,.12,.62)
                scan=sim.scan([.05,0,0])
                pose,_=slam.update(estimate,scan)
                if frame%10==0:
                    state=slam.state(scan,sim.time)
                    path=plan_path(state['grid'],state['origin'],state['resolution'],pose,goal,algorithm=planner)
                linear,angular,status=follow_path(pose,path,goal,scan,controller=controller)
                command=linear,angular
                blocked_frames = blocked_frames+1 if status in ('no_path','obstacle_stop') else 0
                if status=='goal_reached' or blocked_frames >= 30:break
            self.assertEqual(status,'goal_reached',(planner,controller,pose))
            self.assertEqual(sim.collisions,0)
            if status == "goal_reached":
                self.assertLess(math.dist(sim.pose[:2],goal),.4)
            results.append(dict(status=status,goal=goal,planner=planner,controller=controller,simulation_seconds=round(sim.time,2),distance_m=round(distance,3),goal_error_m=round(math.dist(sim.pose[:2],goal),3),collisions=sim.collisions,wall_seconds=round(time.perf_counter()-started,3)))
        output=Path(__file__).resolve().parents[1]/'artifacts/navigation-algorithms.json'
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(results,indent=2))
        print(json.dumps(results))

if __name__=='__main__':unittest.main()
