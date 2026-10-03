# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Physical startup policy and stale placement receipt regressions."""
import sys
import time
import threading
import socket
import unittest
import json
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.simulation.placement_validation import PlacementCheck
from core.simulation.placement_preview import PlacementPreview, fingerprint
from core.simulation.world_catalog import WorldRequest

LEVEL = [1.,0.,0.,0.,1.,0.,0.,0.,1.]


class PlacementTests(unittest.TestCase):
    def sample(self, check, t, **changes):
        values = dict(position=[0,0,0], orientation=LEVEL, velocity=[0]*6,
                      body_contact=False, supported_wheels=4, sensors_ready=True)
        values.update(changes)
        return check.update(t, **values)

    def checker(self):
        return PlacementCheck(dict(spawn_pose=[0,0,0], spawn_height=.002))

    def test_requires_settling_and_continuous_stability(self):
        check=self.checker()
        self.assertEqual(self.sample(check,.1)['status'],'checking')
        self.assertEqual(self.sample(check,2)['status'],'valid')
        self.assertEqual(self.sample(check,2.1,velocity=[.1,0,0,0,0,0])['status'],'invalid')
        self.assertEqual(self.sample(check,2.2)['status'],'invalid')
        self.assertEqual(self.sample(check,2.8)['status'],'valid')

    def test_rejects_missing_floor_body_collision_drift_and_missing_sensors(self):
        for changes in [dict(supported_wheels=0),dict(supported_wheels=3),dict(body_contact=True),
                        dict(position=[.1,0,0]),dict(position=[0,0,-.1]),dict(sensors_ready=False),
                        dict(orientation=[1,0,0,0,1,0,0,0,.8])]:
            with self.subTest(changes=changes):
                check=self.checker()
                self.sample(check,.1)
                result=self.sample(check,2,**changes)
                self.assertEqual(result['status'],'invalid')
                self.assertTrue(result['reasons'])

    def test_receipt_binds_robot_revision_world_hash_and_pose(self):
        request=WorldRequest(path='room.wbt',revision='robot-v1',source_hash='world-v1',placement_token='token')
        preview=PlacementPreview.__new__(PlacementPreview)
        preview.token='token';preview.fingerprint=fingerprint(request)
        preview.stop=threading.Event();preview.error=None
        preview.searched=False
        preview.node=Mock(placement_result={'status':'valid','reasons':[]},placement_updated=time.monotonic())
        preview.require_valid(request)
        for changes in [dict(revision='robot-v2'),dict(source_hash='world-v2'),dict(spawn_pose=[1,0,0]),dict(placement_token='old')]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                preview.require_valid(request.model_copy(update=changes))
        preview.node.placement_updated=time.monotonic()-5
        with self.assertRaises(ValueError):preview.require_valid(request)
        preview.stop.set()
        self.assertEqual(preview.status()['status'],'failed')

    def test_visually_moved_robot_requires_explicit_adoption_but_exposes_safe_pose(self):
        check=self.checker()
        self.sample(check,.1,position=[2,1,.2])
        result=self.sample(check,2,position=[2,1,.2])
        self.assertEqual(result['status'],'invalid')
        self.assertTrue(result['can_use_observed'])
        result=self.sample(check,2.1,position=[2,1,.2],body_contact=True)
        self.assertFalse(result['can_use_observed'])
        result=self.sample(check,2.2,position=[2,1,.2])
        self.assertFalse(result['can_use_observed'])

    def test_paused_preview_keeps_connection_open_until_cancelled(self):
        from plugins.user.webots_sim import WebotsSimulation
        node=WebotsSimulation(node_id='preview',bus=Mock())
        node.placement_preview=True
        node._diagnostic=Mock()
        local,remote=socket.socketpair()
        remote.settimeout(2)
        node._server=Mock()
        node._server.accept.return_value=(local,None)
        worker=threading.Thread(target=node._run,args=('test',))
        try:
            worker.start()
            remote.sendall(b'{"token":"test"}\n{"startup":{"status":"valid","reasons":[]}}\n')
            self.assertIn(b'"linear":0',remote.recv(1000).replace(b' ',b''))
            self.assertIsNone(local.gettimeout())
            self.assertTrue(worker.is_alive())
            self.assertIsNone(node.error)
        finally:
            node._stop.set()
            remote.close()
            worker.join(timeout=3)
            local.close()
        self.assertFalse(worker.is_alive())

    def test_controller_ignores_commands_until_ready_and_throughout_preview(self):
        from core.simulation import webots_controller, placement_validation, placement_search
        for preview, settles_at in ((False,0), (True,0), (False,2.1), (False,20)):
            with self.subTest(preview=preview,settles_at=settles_at):
                clock=[0]
                motor_calls=[]
                supervisor=Mock()
                def step(_):
                    clock[0]+=1
                    return -1 if clock[0]>440 else 0
                supervisor.step.side_effect=step
                supervisor.getTime.side_effect=lambda:clock[0]*.02
                devices={}
                for name in ['a','b','c','d']:
                    motor=Mock()
                    motor.setVelocity.side_effect=lambda v:motor_calls.append((clock[0]*.02,v))
                    devices[name]=motor
                    devices[name+'_encoder']=Mock(getValue=lambda:0.)
                devices['lidar']=Mock(getRangeImage=lambda:[2.]*360,getFov=lambda:6.283185307)
                devices['camera']=Mock(getImage=lambda:b'pixels')
                devices['imu_gyro']=Mock(getValues=lambda:[0,0,0])
                supervisor.getDevice.side_effect=devices.__getitem__
                body=Mock(getPosition=lambda:[0,0,0],getOrientation=lambda:LEVEL,
                          getVelocity=lambda:[.03 if clock[0]*.02<settles_at else 0,0,0,0,0,0],getContactPoints=lambda _:[])
                supervisor.getSelf.return_value=body
                wheel=Mock(getPosition=lambda:[0,0,.1],
                           getContactPoints=lambda _:[SimpleNamespace(point=[0,0,0])])
                supervisor.getFromDef.return_value=wheel
                stream=Mock(readline=lambda _:b'{"linear":0.8,"angular":0}\n')
                packets=[]
                stream.write.side_effect=lambda raw:packets.append(json.loads(raw))
                connection=Mock();connection.makefile.return_value=stream
                info=dict(config=dict(spawn_pose=[0,0,0],spawn_height=.002,
                                      drive=dict(lidar_frame='lidar'),physics=dict(motor_max_velocity=2)),joints=['a','b','c','d'],
                          mounts=dict(lidar_link=[0,0,0]),radius=.1,track=.4,placement_preview=preview)
                with patch.dict(sys.modules,{'controller':SimpleNamespace(Supervisor=lambda:supervisor),
                                             'placement_validation':placement_validation,'placement_search':placement_search}), \
                     patch.object(webots_controller.Path,'read_text',return_value=json.dumps(info)), \
                     patch.object(webots_controller.socket,'create_connection',return_value=connection), \
                     patch.object(sys,'argv',['controller','1234','token']):
                    webots_controller.main()
                if settles_at==20:
                    self.assertTrue(any('Unsafe startup' in packet.get('error','') for packet in packets))
                    self.assertFalse(any(v!=0 for _,v in motor_calls))
                    self.assertFalse(any('scan' in packet for packet in packets))
                    continue
                self.assertFalse(any('error' in packet for packet in packets),packets)
                self.assertTrue(all(abs(v)<=2 for _,v in motor_calls))
                self.assertFalse(any(t<=2 and v!=0 for t,v in motor_calls))
                self.assertFalse(any(t<settles_at+.5 and v!=0 for t,v in motor_calls))
                if preview:
                    self.assertFalse(any(v!=0 for _,v in motor_calls))
                    self.assertFalse(any('scan' in packet for packet in packets))
                else:
                    self.assertTrue(any(t>2 and v!=0 for t,v in motor_calls))
                    self.assertTrue(any('scan' in packet for packet in packets))


if __name__=='__main__':unittest.main()
