# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Deterministic navigation failure/retry checks without sleeping or hardware."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plugins.user.astar_navigation import AStarNavigation
from core.messages import NavigationPath


class RecoveryTests(unittest.TestCase):
    def node(self, **params):
        node = AStarNavigation(node_id='nav', bus=Mock(), params={'goal_x':2., 'goal_y':0., **params})
        node.emit = Mock()
        with patch.object(node,'start_worker'), patch('plugins.user.astar_navigation.time.monotonic',return_value=0.):
            node.on_start()
        return node

    def observation(self, stamp, x=0., blocked=False):
        return {'time':stamp, 'pose':[x,0.,0.], 'grid':[[100 if blocked else 0]*40 for _ in range(40)],
                'origin':[-2.,-2.], 'resolution':.2,
                'scan':{'angles':[-.2,0.,.2], 'ranges':[9.,9.,9.], 'offset':[0.,0.,0.]}}

    def send(self, node, wall, stamp, **kwargs):
        with patch('plugins.user.astar_navigation.time.monotonic',return_value=wall):
            node.process('state',self.observation(stamp,**kwargs))
        report = node.emit.call_args.args[1]
        NavigationPath.model_validate(report)
        return report

    def assert_stopped(self, node):
        command = [call.args[1] for call in node.emit.call_args_list if call.args[0]=='cmd_vel'][-1]
        self.assertEqual((command['linear'],command['angular']),(0.,0.))

    def test_no_route_retries_are_bounded_and_failure_latches(self):
        node = self.node(blocked_timeout=2.)
        for i in range(11):
            report = self.send(node,i*.2,1.+i*.2,blocked=True)
        self.assertEqual(report['status'],'navigation_failed')
        self.assertLessEqual(node.replans,3)
        self.assert_stopped(node)
        # A suddenly free map must not restart a failed mission automatically.
        self.assertEqual(self.send(node,2.2,3.2)['status'],'navigation_failed')
        self.assert_stopped(node)
        node.params['enabled']=True
        node.on_params_changed({'enabled':True})
        self.assertEqual(self.send(node,2.4,3.4)['status'],'navigating')

    def test_progress_watchdog_and_real_translation(self):
        node = self.node(progress_timeout=2.)
        self.send(node,0.,1.)
        self.assertEqual(self.send(node,2.,3.)['status'],'stalled')
        self.assert_stopped(node)
        node = self.node(progress_timeout=2.)
        for i in range(5):
            self.assertEqual(self.send(node,float(i),1.+i,x=.1*i)['status'],'navigating')

    def test_commanded_turn_counts_as_progress_but_frozen_turn_stalls(self):
        node = self.node(progress_timeout=2.)
        with patch('plugins.user.astar_navigation.follow_path',return_value=(0.,.8,'navigating')):
            for i in range(5):
                observation = self.observation(1.+i)
                observation['pose'][2] = .2*i
                with patch('plugins.user.astar_navigation.time.monotonic',return_value=float(i)):
                    node.process('state',observation)
                self.assertEqual(node.emit.call_args.args[1]['status'],'navigating')
            observation['time'] = 7.
            with patch('plugins.user.astar_navigation.time.monotonic',return_value=6.):
                node.process('state',observation)
            self.assertEqual(node.emit.call_args.args[1]['status'],'stalled')
            self.assert_stopped(node)

    def test_duplicate_observations_do_not_feed_watchdog_and_recovery_replans(self):
        node = self.node()
        self.send(node,0.,1.)
        with patch('plugins.user.astar_navigation.time.monotonic',return_value=2.):
            node.process('state',self.observation(1.))
            node.on_tick()
        self.assertEqual(node.emit.call_args.args[1]['status'],'sensor_timeout')
        self.assert_stopped(node)
        plans = node.replans
        self.send(node,2.1,1.1)
        self.assertEqual(node.replans,plans+1)

    def test_changed_goal_discards_old_heartbeat_until_fresh_observation(self):
        node = self.node()
        self.send(node,0.,1.)
        node.params['goal_y']=1.
        node.on_params_changed({'goal_y':1.})
        self.assert_stopped(node)
        node.emit.reset_mock()
        with patch('plugins.user.astar_navigation.time.monotonic',return_value=.2):
            node.on_tick()
        node.emit.assert_not_called()
        self.assertEqual(self.send(node,.3,1.3)['goal'],[2.,1.])

    def test_pause_resets_progress_budget_and_stopped_edits_are_valid(self):
        node = self.node(progress_timeout=2.)
        self.send(node,0.,1.)
        node.params['enabled']=False
        node.on_params_changed({'enabled':False})
        self.assertEqual(self.send(node,10.,11.)['status'],'paused')
        node.params['enabled']=True
        node.on_params_changed({'enabled':True})
        self.assertEqual(self.send(node,11.,12.)['status'],'navigating')
        unstarted = AStarNavigation(node_id='new',bus=Mock())
        unstarted.emit=Mock()
        unstarted.params['enabled']=False
        unstarted.on_params_changed({'enabled':False})
        self.assert_stopped(unstarted)

    def test_obstacle_stops_rotation_as_well_as_translation(self):
        node = self.node()
        with patch('plugins.user.astar_navigation.follow_path',return_value=(0.,.8,'obstacle_stop')):
            self.assertEqual(self.send(node,0.,1.)['status'],'obstacle_stop')
        self.assert_stopped(node)
        self.assertEqual(self.send(node,.5,1.5)['status'],'navigating')

    def test_blocked_wait_does_not_consume_motion_progress_budget(self):
        node=self.node(blocked_timeout=8.,progress_timeout=2.)
        for wall in (0.,1.,3.,6.):
            report=self.send(node,wall,wall+1,blocked=True)
            self.assertEqual(report['status'],'no_path')
            self.assertEqual(report['mission_state'],'recovering')
            self.assert_stopped(node)
        # The obstruction clears before its timeout. Give the drive a fresh
        # progress budget; no motion was commanded during the blocked interval.
        self.assertEqual(self.send(node,6.2,7.2)['status'],'no_path')  # Replan is rate-limited.
        self.assertEqual(self.send(node,7.1,8.1)['status'],'navigating')
        self.assertEqual(self.send(node,8.5,9.5)['status'],'navigating')
        self.assertEqual(self.send(node,9.2,10.2)['status'],'stalled')
        self.assert_stopped(node)

    def test_persistent_obstruction_uses_blocked_timeout_then_requires_retry(self):
        node=self.node(blocked_timeout=4.,progress_timeout=1.)
        for wall in (0.,1.,2.,3.):
            self.assertEqual(self.send(node,wall,wall+1,blocked=True)['status'],'no_path')
        self.assertEqual(self.send(node,4.,5.,blocked=True)['status'],'navigation_failed')
        self.assertEqual(self.send(node,4.2,5.2)['status'],'navigation_failed')
        self.assert_stopped(node)

    def test_new_barrier_replans_detour_without_changing_mission(self):
        node=self.node()
        first=self.send(node,0.,1.)
        observation=self.observation(2.1)
        # Block the old straight route while retaining a wide route around it.
        for row in range(7,14):
            observation['grid'][row][15]=100
        with patch('plugins.user.astar_navigation.time.monotonic',return_value=1.1):
            node.process('state',observation)
        report=node.emit.call_args.args[1]
        self.assertEqual(report['mission_id'],first['mission_id'])
        self.assertEqual(report['status'],'navigating')
        self.assertGreater(report['replans'],first['replans'])
        self.assertTrue(any(abs(point[1])>1. for point in report['points']))

    def test_lidar_obstruction_clears_before_timeout_and_resumes_same_mission(self):
        node=self.node(blocked_timeout=8.,progress_timeout=1.)
        first=self.send(node,0.,1.)
        for wall in (.2,2.,3.,4.):
            observation=self.observation(wall+1)
            observation['scan']['ranges']=[.2]*3
            with patch('plugins.user.astar_navigation.time.monotonic',return_value=wall):
                node.process('state',observation)
            self.assertEqual(node.emit.call_args.args[1]['status'],'obstacle_stop')
            self.assert_stopped(node)
        report=self.send(node,4.2,5.2)
        self.assertEqual(report['status'],'navigating')
        self.assertEqual(report['mission_id'],first['mission_id'])

    def test_alternating_obstruction_does_not_erase_unproductive_driving(self):
        node=self.node(blocked_timeout=8.,progress_timeout=1.)
        self.send(node,0.,1.)
        for wall in (.4,1.4):
            observation=self.observation(wall+1)
            observation['scan']['ranges']=[.2]*3
            with patch('plugins.user.astar_navigation.time.monotonic',return_value=wall):
                node.process('state',observation)
            self.assertEqual(node.emit.call_args.args[1]['status'],'obstacle_stop')
            self.assertEqual(self.send(node,wall+.5,wall+1.5)['status'],'navigating')
        self.assertEqual(self.send(node,2.2,3.2)['status'],'stalled')
        self.assert_stopped(node)


if __name__=='__main__': unittest.main()
