"""Built-in reference robot: inputs/outputs can later be replaced by drivers."""
import base64
import threading
import time
import cv2
import numpy as np

from sdk.pyrobot_plugin import Node, PluginManifest, PortSpec, PortDataType as T, ParamSpec
from core.simulation.world import FourWheelSimulator, robot_dimensions, sensor_pose, camera_image, collision


class FourWheelSimulation(Node):
    manifest = PluginManifest(
        id="pyrobot.sim.four_wheel", name="Four-wheel simulator", category="Simulation",
        description="Planar four-wheel drive in a 3D room. Ray-cast 360 lidar, wheel encoders and a perspective camera. No full wheel physics.",
        inputs=[PortSpec("cmd_vel", T.JSON, schema="pyrobot/VelocityCommand@1")],
        outputs=[PortSpec("sensors", T.JSON, schema="pyrobot/SensorPacket@1"), PortSpec("truth", T.JSON), PortSpec("camera", T.IMAGE, schema="pyrobot/Image@1")],
        params=[ParamSpec("speed", "number", default=1.0, min=.25, max=3),
                ParamSpec("encoder_bias", "number", default=.01, min=0, max=.05)],
        requires_urdf_link=True,
    )

    def validate_configuration(self):
        if self.robot_config.webots_world:
            raise ValueError("External Webots worlds require the Webots simulator")
        robot_dimensions(self.robot_model, self.robot_config)
        from core.simulation.mesh_robot import validate_simulation_model
        validate_simulation_model(self.robot_model, self.robot_config)
        if self.urdf_link != self.robot_config.drive.base_frame:
            raise ValueError("Simulator URDF binding must match configured base_frame")
        if collision(np.asarray(self.robot_config.spawn_pose), self.robot_config.drive.collision_radius, self.robot_config.environment.boxes()):
            raise ValueError("Robot starting position collides with the configured environment")

    def on_start(self):
        self._stop = threading.Event()
        self.radius, self.track, self.mounts = robot_dimensions(self.robot_model, self.robot_config)
        self.sim = FourWheelSimulator(self.radius, self.track, configuration=self.robot_config)
        self._command_lock = threading.Lock()
        self._command = (0.0, 0.0, 0.0)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=self.node_id, daemon=True)
        self._thread.start()

    def on_message(self, port, message):
        payload = message.payload
        if payload["frame"] != self.robot_config.drive.base_frame:
            raise ValueError("Velocity command frame does not match the configured robot base")
        linear, angular = float(payload.get("linear", 0)), float(payload.get("angular", 0))
        if not np.isfinite([linear, angular]).all():
            linear = angular = 0
        with self._command_lock:
            self._command = (linear, angular, time.monotonic())

    def on_stop(self):
        self._stop.set()

    def on_params_changed(self, updated):
        if "encoder_bias" in updated:
            raise ValueError("Stop the graph before changing encoder_bias")

    def _run(self):
        frame = 0
        deadline = time.monotonic() + .1 / self.get_param("speed", 1.0)
        try:
            while not self._stop.wait(max(0., deadline - time.monotonic())):
                with self._command_lock:
                    linear, angular, received = self._command
                if time.monotonic()-received > .6:
                    linear = angular = 0.0
                blocked = self.sim.step(linear, angular, .1)
                captured = self.capture_time(self.sim.time)
                metadata = dict(timestamp=captured, clock_domain="simulation")
                drive = self.robot_config.drive
                bias = self.get_param("encoder_bias", .01)
                ticks = np.rint(self.sim.wheels * np.array([1+bias,1+bias,1-bias*.5,1-bias*.5]) * drive.ticks_per_turn/(2*np.pi)).astype(int)
                scan = self.sim.scan(self.mounts["lidar_link"])
                self.emit("sensors", {"ticks": ticks.tolist(), "wheel_radius": self.radius,
                    "frame": drive.base_frame, "track": self.track, "ticks_per_turn": drive.ticks_per_turn, "scan": scan, "time": self.sim.time}, **metadata)
                self.emit("truth", {"pose": self.sim.pose.tolist(), "wheels": self.sim.wheels.tolist(),
                    "time": self.sim.time, "collisions": self.sim.collisions, "blocked": blocked,
                    "joint_names": drive.left_joints + drive.right_joints,
                    "bounds": self.robot_config.environment.bounds, "obstacles": self.sim.obstacles}, **metadata)
                if frame % 2 == 0:
                    image = camera_image(sensor_pose(self.sim.pose, self.mounts["camera_link"]),
                                         camera_height=self.mounts["camera_link_height"], obstacles=self.sim.obstacles)
                    ok, jpeg = cv2.imencode(".jpg", cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
                    if ok:
                        self.emit("camera", {"jpeg_base64": base64.b64encode(jpeg).decode("ascii"),
                            "width": image.shape[1], "height": image.shape[0], "time": self.sim.time,
                            "frame": drive.camera_frame, "source": "geometric-simulation"}, **metadata)
                frame += 1
                # Include sensor/render work in the frame budget. Never burst
                # old frames to catch up when the machine is overloaded.
                period = .1 / self.get_param("speed", 1.0)
                deadline += period
                if deadline < time.monotonic():
                    deadline = time.monotonic() + period
        except Exception as exc:
            self.fail(exc)
            self.log.exception("Simulation failed")
            self._stop.set()
