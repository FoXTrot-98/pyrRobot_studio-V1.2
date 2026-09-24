"""Joint telemetry and camera visualization for native Webots examples."""
import base64
import cv2
import numpy as np
import rerun as rr
import rerun.blueprint as rrb
from sdk.pyrobot_plugin import PluginManifest, PortSpec, PortDataType as T
from core.simulation.worker import WorkerNode


class WebotsModelView(WorkerNode):
    manifest=PluginManifest(id='pyrobot.sim.webots_model_view',name='Webots joints / Rerun',category='Visualization',
        description='Measured joints and camera. The original full 3D robot/world is rendered in the Webots window.',
        inputs=[PortSpec('state',T.JSON,schema='pyrobot/WebotsRobotState@1'),
                PortSpec('camera',T.IMAGE,required=False,schema='pyrobot/Image@1')])

    def on_start(self):
        if rr.get_application_id() is None: rr.init('pyrobot-native-webots',spawn=False)
        rr.send_blueprint(rrb.Blueprint(rrb.Horizontal(rrb.TimeSeriesView(origin='/native/joints',name='Measured joints'),
            rrb.Vertical(rrb.Spatial2DView(origin='/native/camera',name='Robot camera'),rrb.TextDocumentView(origin='/native/status',name='Robot status'))),collapse_panels=True))
        self.start_worker()

    def process(self,port,payload):
        rr.set_time('simulation_time',duration=payload['time'])
        if port=='state':
            for joint in payload['joints']: rr.log(f"native/joints/{joint['name']}",rr.Scalars(joint['position']))
            rr.log('native/status',rr.TextDocument(f"{payload['profile']}: {payload['status']}\n{payload['error']}\n\n3D robot and world: Webots window. Joint values: rad / m as reported in Studio."))
        else:
            pixels=cv2.imdecode(np.frombuffer(base64.b64decode(payload['jpeg_base64']),dtype=np.uint8),cv2.IMREAD_COLOR)
            rr.log('native/camera',rr.Image(cv2.cvtColor(pixels,cv2.COLOR_BGR2RGB)))
