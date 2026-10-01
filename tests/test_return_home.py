# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Home capture, persistence, preemption, arrival and unreachable-home behavior."""
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from plugins.user.astar_navigation import AStarNavigation
from core.messages import NavigationPath


class HomeTests(unittest.TestCase):
    def node(self, **params):
        node=AStarNavigation(node_id='nav',bus=Mock(),params={'goal_x':2.,'goal_y':0.,**params})
        node.emit=Mock()
        with patch.object(node,'start_worker'):
            node.on_start()
        return node

    def send(self,node,t,pose,blocked=False):
        with patch('plugins.user.astar_navigation.time.monotonic',return_value=t):
            node.process('state',{'time':t,'pose':pose,'grid':[[100 if blocked else 0]*40 for _ in range(40)],
                                  'origin':[-2.,-2.],'resolution':.2,
                                  'scan':{'angles':[0.],'ranges':[9.],'offset':[0.,0.,0.]}})
        result=node.emit.call_args.args[1]
        NavigationPath.model_validate(result)
        return result

    def change(self,node,**params):
        node.params.update(params)
        node.on_params_changed(params)

    def stopped(self,node):
        cmd=[c.args[1] for c in node.emit.call_args_list if c.args[0]=='cmd_vel'][-1]
        self.assertEqual((cmd['linear'],cmd['angular']),(0.,0.))

    def test_auto_capture_preempts_waypoints_aligns_and_latches_arrival(self):
        node=self.node(waypoints=[[2.,0.]])
        home=[0.,0.,1.]
        self.assertEqual(self.send(node,1.,home)['home_pose'],home)
        self.send(node,2.,[1.,0.,0.])
        self.change(node,return_home=True,enabled=True)
        self.stopped(node)
        result=self.send(node,3.,[1.,0.,0.])
        self.assertEqual(result['goal'],[0.,0.])
        self.assertEqual(result['waypoints'],[])
        self.assertEqual(result['status'],'returning_home')
        self.assertEqual(self.send(node,4.,[0.,0.,0.])['status'],'aligning_home')
        self.assertEqual(self.send(node,5.,home)['status'],'home_reached')
        self.stopped(node)
        self.assertEqual(self.send(node,6.,[1.,0.,0.])['status'],'home_reached')
        self.stopped(node)
        self.assertEqual(node.params['waypoints'],[[2.,0.]])

    def test_unreachable_home_failure_survives_sensor_timeout_and_requires_retry(self):
        node=self.node(home_pose=[1.,0.,0.],return_home=True,blocked_timeout=1.)
        self.send(node,1.,[0.,0.,0.],blocked=True)
        report=self.send(node,2.,[0.,0.,0.],blocked=True)
        self.assertEqual(report['status'],'navigation_failed')
        self.assertTrue(report['returning_home'])
        self.stopped(node)
        with patch('plugins.user.astar_navigation.time.monotonic',return_value=4.):node.on_tick()
        self.assertEqual(self.send(node,5.,[0.,0.,0.])['status'],'navigation_failed')
        self.change(node,enabled=True)
        self.assertEqual(self.send(node,6.,[0.,0.,0.])['status'],'returning_home')

    def test_pause_cancel_and_restart_home_capture(self):
        node=self.node(return_home=True,enabled=False)
        self.assertEqual(self.send(node,1.,[0.,0.,0.])['status'],'paused')
        self.assertFalse(node._home_reached)
        self.change(node,return_home=False,enabled=True)
        self.assertEqual(self.send(node,2.,[0.,0.,0.])['status'],'navigating')
        with patch.object(node,'start_worker'):node.on_start()
        self.assertEqual(self.send(node,1.,[.5,0.,0.])['home_pose'],[.5,0.,0.])

    def test_invalid_home_and_heading_wrap(self):
        for home in (None,[0,0],[0,0,float('nan')],[999,0,0],['a',0,0]):
            with self.subTest(home=home),self.assertRaises(ValueError):self.node(home_pose=home).validate_configuration()
        node=self.node(home_pose=[0.,0.,math.pi-.02],return_home=True)
        self.assertEqual(self.send(node,1.,[0.,0.,-math.pi+.02])['status'],'home_reached')

    def test_saved_home_survives_project_roundtrip(self):
        from fastapi.testclient import TestClient
        from backend.app import main
        with patch.object(main,'init_rerun'),TestClient(main.app) as client:
            response=client.post('/api/graph/nodes',json={'node_id':'nav','plugin_id':'pyrobot.navigation.astar'})
            self.assertEqual(response.status_code,200,response.text)
            response=client.patch('/api/graph/nodes/nav/params',json={'params':{'home_pose':[.5,.2,1.],'return_home':True,'enabled':False,'planner':'dijkstra','controller':'fuzzy'}})
            self.assertEqual(response.status_code,200,response.text)
            saved=client.post('/api/project/export',json={'name':'Home test','positions':{}}).json()
            response=client.post('/api/project/import',json=saved)
            self.assertEqual(response.status_code,200,response.text)
            node=main.runtime.graph.nodes['nav'].node_obj
            self.assertEqual(node.get_param('home_pose'),[.5,.2,1.])
            self.assertEqual(node.get_param('planner'),'dijkstra')
            self.assertEqual(node.get_param('controller'),'fuzzy')
            self.assertTrue(node.get_param('return_home'))
            self.assertFalse(main.runtime.graph.to_dict()['running'])


if __name__=='__main__':unittest.main()
