# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Run native Webots examples without the four-wheel URDF assumptions."""
import base64
import json
import os
import socket
import subprocess
import threading
import time
import uuid
import cv2
import numpy as np
from sdk.pyrobot_plugin import PluginManifest, PortSpec, PortDataType as T, ParamSpec
from plugins.user.webots_sim import WebotsSimulation
from core.simulation.webots_project import find_webots, ROOT
from core.simulation.webots_examples import PROFILES, example_world, prepare_example


class WebotsModel(WebotsSimulation):
    manifest=PluginManifest(id='pyrobot.sim.webots_model',name='Webots existing robot',category='Simulation',
        description='Run the original Panda, NAO or youBot world with Studio controls and joint telemetry. Native PROTO assets; no four-wheel URDF required.',
        inputs=[PortSpec('targets',T.JSON,required=False,schema='pyrobot/JointTargets@1'),
                PortSpec('cmd_vel',T.JSON,required=False,schema='pyrobot/VelocityCommand@1')],
        outputs=[PortSpec('state',T.JSON,schema='pyrobot/WebotsRobotState@1'),PortSpec('camera',T.IMAGE,schema='pyrobot/Image@1')],
        params=[ParamSpec('profile','enum',default='panda',options=list(PROFILES)),
                ParamSpec('action','enum',default='hold',options=sorted({a for p in PROFILES.values() for a in p['actions']})),
                ParamSpec('executable','file',default=''),ParamSpec('minimize','bool',default=False)])

    def validate_configuration(self):
        profile=self.get_param('profile','panda')
        if profile not in PROFILES: raise ValueError('Unknown Webots example profile')
        if self.get_param('action','hold') not in PROFILES[profile]['actions']:
            raise ValueError(f'Action is not supported by {profile}')
        example_world(profile,self.get_param('executable',''))

    def on_start(self):
        self._stop=threading.Event()
        self._command={'id':uuid.uuid4().hex,'action':'hold'}
        self._velocity=(0.,0.,0.)
        self._server=socket.socket(); self._server.bind(('127.0.0.1',0)); self._server.listen(1); self._server.settimeout(.2)
        token=uuid.uuid4().hex; self.directory=ROOT/'artifacts/webots-examples'/token
        world=prepare_example(self.directory,self.get_param('profile','panda'),self.get_param('executable',''),self._server.getsockname()[1],token)
        self._log_file=(self.directory/'webots.log').open('w',encoding='utf-8')
        command=[find_webots(self.get_param('executable','')),'--batch','--mode=realtime','--stdout','--stderr']
        if self.get_param('minimize',False): command.append('--minimize')
        self._process=subprocess.Popen(command+[str(world)],stdout=self._log_file,stderr=self._log_file,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        self._thread=threading.Thread(target=self._run,args=(token,),name=self.node_id,daemon=True); self._thread.start()

    def update_params(self, updates):
        if self._running and set(updates)-{'action'}:
            raise ValueError('Stop the graph before changing Webots profile or launch settings')
        with self._command_lock:
            super().update_params(updates)

    def on_params_changed(self, updated):
        self.validate_configuration()
        if 'action' in updated:
            self._command={'id':uuid.uuid4().hex,'action':updated['action']}
            if updated['action']=='hold': self._velocity=(0.,0.,0.)

    def on_message(self, port, message):
        with self._command_lock:
            if port=='targets':
                if message.payload['frame']!='robot': raise ValueError('Joint targets must use the robot frame')
                self._command={'id':uuid.uuid4().hex,'action':'targets','targets':message.payload['positions']}
            elif port=='cmd_vel':
                if self.get_param('profile')!='youbot': raise ValueError('Only the youBot profile accepts base velocity')
                if message.payload['frame']!='base_link': raise ValueError('Base commands must use base_link')
                self._velocity=(message.payload['linear'],message.payload['angular'],time.monotonic())

    def _run(self, token):
        try:
            deadline=time.monotonic()+180
            while not self._stop.is_set():
                try: self._connection,_=self._server.accept(); break
                except socket.timeout:
                    if self._process.poll() is not None or time.monotonic()>deadline:
                        raise RuntimeError(f'Webots example did not connect. First use may need model downloads; see {self.directory / "webots.log"}')
            if self._stop.is_set(): return
            self._connection.settimeout(10.)
            stream=self._connection.makefile('rwb')
            if json.loads(stream.readline(4096)).get('token')!=token: raise ValueError('Unexpected controller token')
            last_time=-1.
            while not self._stop.is_set():
                raw=stream.readline(4*1024*1024)
                if not raw or not raw.endswith(b'\n'): raise RuntimeError('Webots controller disconnected or packet too large')
                packet=json.loads(raw); now=packet['time']
                if now<=last_time: raise ValueError('Simulation reset: stop and restart the Studio graph')
                last_time=now
                with self._command_lock:
                    command=dict(self._command); linear,angular,received=self._velocity
                if time.monotonic()-received>.35: linear=angular=0.
                command.update(linear=linear,angular=angular)
                stream.write((json.dumps(command)+'\n').encode()); stream.flush()
                camera=packet.pop('camera',None)
                metadata={'timestamp':self.capture_time(now),'clock_domain':'simulation'}
                self.emit('state',packet,**metadata)
                if camera:
                    width,height=camera['width'],camera['height']
                    pixels=np.frombuffer(base64.b64decode(camera['bgra'],validate=True),dtype=np.uint8).reshape(height,width,4)
                    ok,jpeg=cv2.imencode('.jpg',cv2.cvtColor(pixels,cv2.COLOR_BGRA2BGR))
                    if ok: self.emit('camera',{'width':width,'height':height,'jpeg_base64':base64.b64encode(jpeg).decode(),
                        'frame':camera['name'],'time':now,'source':'webots'},**metadata)
        except Exception as exc:
            if not self._stop.is_set(): self.fail(exc)
