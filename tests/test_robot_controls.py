# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

import sys
import threading
from dataclasses import replace
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.timing.clock import PRTClock
from core.bus.base import Bus, BusMessage
from test_runtime_projects import MemoryTransport
from plugins.user.keyboard_teleop import KeyboardTeleop
from plugins.user.command_selector import CommandSelector
from plugins.user.astar_navigation import AStarNavigation
from core.simulation.navigation import LidarSlam
from core.simulation.world import FourWheelSimulator


class ControlsTests(unittest.TestCase):
    def setUp(self):
        clock = PRTClock("test")
        clock.set_epoch_origin(time.time_ns())
        self.bus = Bus(MemoryTransport(), clock)

    def tearDown(self):
        self.bus.close()

    def test_keyboard_expiry_focus_release_and_sequence(self):
        node = KeyboardTeleop(node_id="keyboard", bus=self.bus)
        node.acquire("tab1")
        with self.assertRaises(ValueError): node.acquire("tab2")
        node.accept_keys("tab1", 0, ["KeyW", "KeyA"])
        node.capture_time()  # Publication sequence is independent of browser sequence.
        node.accept_keys("tab1", 1, ["KeyW"])
        self.assertEqual(node.command(), (.35, 0.))
        with self.assertRaises(ValueError): node.accept_keys("tab1", 1, ["KeyS"])
        with patch("plugins.user.keyboard_teleop.time.monotonic", return_value=node._received+.31):
            self.assertEqual(node.command(), (0.,0.))
        node.accept_keys("tab1", 2, ["KeyW", "Space"])
        self.assertEqual(node.command(), (0.,0.))
        node.accept_keys("tab1", 3, ["KeyW"])
        node.release("tab1")
        self.assertEqual(node.command(), (0.,0.))

    def test_selector_requires_fresh_command_after_mode_switch(self):
        node = CommandSelector(node_id="drive", bus=self.bus, params={"mode":"manual"})
        node.emit = Mock()
        message = BusMessage("test", {"linear":.3,"angular":0.,"time":1.,"frame":"base_link"}, self.bus._clock.now())
        node.on_message("manual", message)
        node._publish()
        self.assertEqual(node.emit.call_args.args[1]["linear"], .3)
        node.params["mode"] = "autonomous"
        node.on_params_changed({"mode":"autonomous"})
        self.assertEqual(node.emit.call_args.args[1]["linear"], 0)
        node.on_message("autonomous", message)
        with patch("plugins.user.command_selector.time.monotonic", return_value=time.monotonic()+.5):
            node._publish()
        self.assertEqual(node.emit.call_args.args[1]["linear"], 0)

    def test_delayed_command_cannot_cross_mode_transition(self):
        node=CommandSelector(node_id="drive",bus=self.bus,params={"mode":"manual"})
        node.emit=Mock()
        stamp=self.bus._clock.now()
        old=BusMessage("test",{"linear":.65,"angular":0.,"time":1.,"frame":"base_link"},stamp,published_timestamp=stamp)
        node.params['mode']='autonomous'
        node.on_params_changed({'mode':'autonomous'})
        # Queued before the switch, delivered after it: must not move the robot.
        node.on_message('autonomous',old)
        node._publish()
        self.assertEqual(node.emit.call_args.args[1]['linear'],0.)
        fresh=replace(old,timestamp=replace(stamp,epoch_ns=900_000_000_000),clock_domain="simulation",published_timestamp=self.bus._clock.now())
        node.on_message('autonomous',fresh)
        node._publish()
        self.assertEqual(node.emit.call_args.args[1]['linear'],.65)
        stopped=replace(fresh,payload={**fresh.payload,'linear':0.},published_timestamp=self.bus._clock.now())
        node.on_message('autonomous',stopped)
        node.on_message('autonomous',fresh)
        node._publish()
        self.assertEqual(node.emit.call_args.args[1]['linear'],0.)
        expired=replace(fresh,published_timestamp=replace(self.bus._clock.now(),epoch_ns=self.bus._clock.now().epoch_ns-500_000_000))
        node._commands.clear()
        node.on_message('autonomous',expired)
        node._publish()
        self.assertEqual(node.emit.call_args.args[1]['linear'],0.)

    def test_parameter_mutation_waits_for_control_cycle(self):
        for cls,lock_name,key,value in ((AStarNavigation,'_control_lock','goal_x',2.),(CommandSelector,'_command_lock','mode','autonomous')):
            node=cls(node_id='atomic',bus=self.bus)
            previous=node.get_param(key)
            entered=threading.Event()
            done=threading.Event()
            def update():
                entered.set()
                node.update_params({key:value})
                done.set()
            with getattr(node,lock_name):
                worker=threading.Thread(target=update)
                worker.start()
                self.assertTrue(entered.wait(1))
                self.assertFalse(done.wait(.05))
                self.assertEqual(node.get_param(key),previous)
            worker.join(1)
            self.assertTrue(done.is_set())
            self.assertEqual(node.get_param(key),value)

    def test_waypoint_order_completion_and_paused_progress(self):
        node = AStarNavigation(node_id="nav", bus=self.bus, params={"waypoints":[[0.,0.],[0.,.5]],"enabled":False})
        node.emit = Mock()
        with patch.object(node,"start_worker"): node.on_start()
        slam, sim = LidarSlam(), FourWheelSimulator()
        scan = sim.scan([.05,0,0])
        slam.update([0,0,0], scan)
        state = slam.state(scan, 1.)
        node.process("state", state)
        self.assertEqual(node.waypoint_index, 0)
        node.params["enabled"] = True
        node.process("state", dict(state,time=2.))
        self.assertEqual(node.waypoint_index, 1)
        node.process("state", dict(state,time=3.,pose=[0.,.5,0.]))
        self.assertEqual(node.emit.call_args.args[1]["status"], "mission_complete")
        self.assertEqual(node.emit.call_args_list[-2].args[1]["linear"], 0.)
        node.process("state", dict(state,time=4.,pose=[0.,0.,0.]))
        self.assertEqual(node.emit.call_args.args[1]["status"], "mission_complete")
        self.assertEqual(node.emit.call_args_list[-2].args[1]["linear"], 0.)
        node.params["waypoints"] = [[999.,0.]]
        with self.assertRaises(ValueError): node.validate_configuration()

    def test_websocket_control_and_disconnect_stop(self):
        from fastapi.testclient import TestClient
        from backend.app import main
        with patch.object(main,"init_rerun"), TestClient(main.app) as client:
            response = client.post("/api/graph/nodes",json={"node_id":"keyboard","plugin_id":"pyrobot.control.keyboard"})
            self.assertEqual(response.status_code,200)
            run = client.post("/api/graph/start").json()["run_id"]
            node = main.runtime.graph.nodes["keyboard"].node_obj
            with client.websocket_connect(f"/ws/control/keyboard?run_id={run}") as ws:
                ws.send_json({"sequence":0,"keys":["KeyW"]})
                deadline = time.monotonic()+1
                while not node.command()[0] and time.monotonic()<deadline: time.sleep(.01)
                self.assertGreater(node.command()[0],0)
            deadline = time.monotonic()+1
            while node.command()[0] and time.monotonic()<deadline: time.sleep(.01)
            self.assertEqual(node.command(),(0.,0.))


if __name__ == "__main__":
    unittest.main()
