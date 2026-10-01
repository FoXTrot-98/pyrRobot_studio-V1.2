# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Mission transitions and motion latches across navigation modes."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import patch
import test_return_home

class MissionTests(unittest.TestCase):
    node = test_return_home.HomeTests.node
    send = test_return_home.HomeTests.send
    change = test_return_home.HomeTests.change
    stopped = test_return_home.HomeTests.stopped

    def test_cancel_survives_resume_and_new_mission_replaces_it(self):
        node=self.node()
        first=self.send(node,1.,[0.,0.,0.])
        self.assertEqual(first['mission_state'],'running')
        self.change(node,cancel_mission=True)
        self.stopped(node)
        self.change(node,enabled=True)
        report=self.send(node,2.,[0.,0.,0.])
        self.assertEqual(report['mission_state'],'cancelled')
        self.assertEqual(report['mission_id'],first['mission_id'])
        self.stopped(node)
        self.change(node,return_home=True)
        report=self.send(node,3.,[1.,0.,0.])
        self.assertEqual(report['mission_type'],'return_home')
        self.assertEqual(report['mission_state'],'running')
        self.assertNotEqual(report['mission_id'],first['mission_id'])

    def test_single_goal_completion_latches_until_new_goal(self):
        node=self.node(goal_x=0.,goal_y=0.)
        report=self.send(node,1.,[0.,0.,0.])
        self.assertEqual(report['mission_state'],'completed')
        self.assertEqual(self.send(node,2.,[1.,0.,0.])['status'],'goal_reached')
        self.stopped(node)
        self.change(node,enabled=False)
        self.change(node,enabled=True)
        self.assertEqual(self.send(node,3.,[1.,0.,0.])['mission_state'],'completed')
        self.change(node,goal_x=2.)
        self.assertEqual(self.send(node,4.,[1.,0.,0.])['mission_state'],'running')

    def test_recovery_sensor_wait_failure_and_explicit_retry(self):
        node=self.node(blocked_timeout=1.)
        self.assertEqual(self.send(node,1.,[0.,0.,0.],True)['mission_state'],'recovering')
        report=self.send(node,2.,[0.,0.,0.],True)
        self.assertEqual(report['mission_state'],'failed')
        self.assertEqual(report['recovery_action'],'retry_or_cancel')
        with patch('plugins.user.astar_navigation.time.monotonic',return_value=4.):node.on_tick()
        self.assertEqual(node.emit.call_args.args[1]['mission_state'],'failed')
        self.change(node,enabled=True)
        report=self.send(node,5.,[0.,0.,0.])
        self.assertEqual(report['mission_state'],'running')
        with patch('plugins.user.astar_navigation.time.monotonic',return_value=7.):node.on_tick()
        self.assertEqual(node.emit.call_args.args[1]['mission_state'],'waiting_for_sensors')
        self.change(node,enabled=False)
        self.assertEqual(self.send(node,8.,[0.,0.,0.])['mission_state'],'paused')

    def test_saved_cancellation_blocks_motion_after_restart(self):
        node=self.node(cancel_mission=True,explore=True)
        report=self.send(node,1.,[0.,0.,0.])
        self.assertEqual(report['mission_type'],'exploration')
        self.assertEqual(report['mission_state'],'cancelled')
        self.stopped(node)
        self.change(node,explore=True)
        self.assertFalse(node.get_param('cancel_mission'))

if __name__=='__main__':unittest.main()
