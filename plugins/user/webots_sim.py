"""Managed Webots physics process; its sensors use the same graph contracts."""
import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
import uuid
import cv2
import numpy as np
from sdk.pyrobot_plugin import Node, PluginManifest, PortSpec, PortDataType as T, ParamSpec
from core.simulation.world import robot_dimensions, collision
from core.simulation.webots_project import generate_project, find_webots, ROOT


class WebotsSimulation(Node):
    manifest = PluginManifest(id="pyrobot.sim.webots", name="Webots four-wheel robot", category="Simulation",
        description="Launches a Webots physics world from the project URDF/configuration. Simulated lidar, camera, motor encoders and an integrated base gyro.",
        inputs=[PortSpec("cmd_vel", T.JSON, schema="pyrobot/VelocityCommand@1")],
        outputs=[PortSpec("sensors", T.JSON, schema="pyrobot/SensorPacket@1"), PortSpec("truth", T.JSON),
                 PortSpec("camera", T.IMAGE, schema="pyrobot/Image@1")],
        params=[ParamSpec("executable", "file", default="", description="Optional Webots executable path; otherwise auto-detected."),
                ParamSpec("minimize", "bool", default=False)], requires_urdf_link=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._command_lock = threading.Lock()
        self._stop = threading.Event()
        self._process = self._server = self._connection = self._log_file = None

    def validate_configuration(self):
        robot_dimensions(self.robot_model, self.robot_config)
        from core.simulation.mesh_robot import collision_body
        collision_body(self.robot_model, self.robot_config)
        if self.urdf_link != self.robot_config.drive.base_frame:
            raise ValueError("Bind Webots to the configured base frame")
        if not find_webots(self.get_param("executable", "")):
            raise ValueError("Webots not found. Install Webots R2025a or set the executable parameter / WEBOTS_EXECUTABLE.")
        if self.robot_config.webots_world:
            from core.simulation.external_world import inspect
            info=inspect(self.robot_config.webots_world,self.get_param('executable',''))
            if info['sha256']!=self.robot_config.webots_world_hash:
                raise ValueError('Source world changed. Check and apply it again in World setup')
            return
        if collision(np.asarray(self.robot_config.spawn_pose), self.robot_config.drive.collision_radius, self.robot_config.environment.boxes()):
            raise ValueError("Starting position collides with the configured environment")

    def on_start(self):
        self._stop = threading.Event()
        self._command = (0., 0., 0.)
        self.radius, self.track, _ = robot_dimensions(self.robot_model, self.robot_config)
        self._server = socket.socket()
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        self._server.settimeout(.2)
        token = uuid.uuid4().hex
        self.directory = ROOT/"artifacts/webots"/token
        world = generate_project(self.directory, self.robot_model, self.robot_config, self._server.getsockname()[1], token, self.get_param('executable',''))
        self._log_file = (self.directory/"webots.log").open("w", encoding="utf-8")
        command = [find_webots(self.get_param("executable", "")), "--batch", "--mode=realtime", "--stdout", "--stderr"]
        if self.get_param("minimize", False): command.append("--minimize")
        command.append(str(world))
        self._process = subprocess.Popen(command, stdout=self._log_file, stderr=self._log_file,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self._thread = threading.Thread(target=self._run, args=(token,), name=self.node_id, daemon=True)
        self._thread.start()

    def on_message(self, port, message):
        if message.payload["frame"] != self.robot_config.drive.base_frame:
            raise ValueError("Command frame does not match Webots base")
        with self._command_lock:
            self._command = (float(np.clip(message.payload["linear"], -.8, .8)),
                float(np.clip(message.payload["angular"], -1.5, 1.5)), time.monotonic())

    def _run(self, token):
        try:
            deadline = time.monotonic()+90
            while not self._stop.is_set():
                try:
                    self._connection, _ = self._server.accept()
                    break
                except socket.timeout:
                    if self._process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError(f"Webots did not connect; see {self.directory / 'webots.log'}")
            if self._stop.is_set(): return
            self._connection.settimeout(5.)
            stream = self._connection.makefile("rwb")
            if json.loads(stream.readline(4096)).get("token") != token:
                raise ValueError("Unexpected Webots controller token")
            drive = self.robot_config.drive
            last_time = -1.
            while not self._stop.is_set():
                raw = stream.readline(2*1024*1024)
                if not raw or not raw.endswith(b"\n"):
                    raise RuntimeError("Webots controller disconnected or packet exceeded limit")
                packet = json.loads(raw)
                if packet.get('error'):
                    raise RuntimeError(packet['error'])
                now = packet["time"]
                if now <= last_time:
                    raise ValueError("Webots simulation clock reset; stop and restart the Studio graph")
                last_time = now
                with self._command_lock:
                    linear, angular, received = self._command
                if time.monotonic()-received > .5: linear = angular = 0.
                stream.write((json.dumps({"linear": linear, "angular": angular})+"\n").encode()); stream.flush()
                captured = self.capture_time(now)
                metadata = dict(timestamp=captured, clock_domain="simulation")
                ticks = np.rint(np.asarray(packet["wheels"])*drive.ticks_per_turn/(2*np.pi)).astype(int).tolist()
                self.emit("sensors", {"ticks": ticks, "wheel_radius": self.radius, "track": self.track,
                    "ticks_per_turn": drive.ticks_per_turn, "scan": packet["scan"], "gyro_yaw": packet.get("gyro_yaw"), "time": now, "frame": drive.base_frame}, **metadata)
                mapping=self.robot_config.mapping
                bounds=[*mapping.origin,mapping.origin[0]+mapping.width*mapping.resolution,mapping.origin[1]+mapping.height*mapping.resolution] if self.robot_config.webots_world else self.robot_config.environment.bounds
                self.emit("truth", {"pose": packet["pose"], "wheels": packet["wheels"], "time": now,
                    "source": "webots",
                    "joint_names": drive.left_joints+drive.right_joints, "bounds": bounds,
                    "obstacles": [] if self.robot_config.webots_world else self.robot_config.environment.boxes(), "collisions": packet["collisions"], "blocked": packet["blocked"]}, **metadata)
                if "camera_bgra" in packet:
                    pixels = np.frombuffer(base64.b64decode(packet["camera_bgra"], validate=True), dtype=np.uint8).reshape(144,240,4)
                    ok, encoded = cv2.imencode(".jpg", cv2.cvtColor(pixels, cv2.COLOR_BGRA2BGR))
                    if ok:
                        self.emit("camera", {"width": 240, "height": 144, "jpeg_base64": base64.b64encode(encoded).decode(),
                            "time": now, "frame": drive.camera_frame, "source": "webots"}, **metadata)
        except Exception as exc:
            if not self._stop.is_set(): self.fail(exc)

    def on_stop(self):
        self._stop.set()
        if self._connection:
            try: self._connection.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            self._connection.close()
        if self._server: self._server.close()
        if self._process and self._process.poll() is None:
            try: self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(self._process.pid), "/T", "/F"],
                        capture_output=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    self._process.terminate()
                self._process.wait(timeout=3)
        if self._log_file: self._log_file.close()
