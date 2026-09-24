import math
import threading
import time
from sdk.pyrobot_plugin import PluginManifest, PortSpec, PortDataType as T, ParamSpec
from core.simulation.worker import WorkerNode
from core.simulation.navigation import plan_path, follow_path


class AStarNavigation(WorkerNode):
    SENSOR_TIMEOUT = 1.5

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._control_lock = threading.RLock()

    manifest = PluginManifest(id="pyrobot.navigation.astar", name="A* navigation", category="Navigation",
        description="Plans through the measured occupancy grid, inflates obstacles and follows a goal. Unknown cells cost more; front lidar provides a local stop.",
        inputs=[PortSpec("state", T.JSON, schema="pyrobot/MappingState@1")], outputs=[PortSpec("cmd_vel", T.JSON, schema="pyrobot/VelocityCommand@1"), PortSpec("path", T.JSON, schema="pyrobot/NavigationPath@1")],
        params=[ParamSpec("goal_x", "number", default=8.0),
                ParamSpec("goal_y", "number", default=6.0),
                ParamSpec("max_speed", "number", default=.65, min=.1, max=.8),
                ParamSpec("waypoints", "json", default=[], description="Ordered map coordinates in metres, configured by clicking the SLAM map."),
                ParamSpec("enabled", "bool", default=True)])

    def validate_configuration(self):
        m = self.robot_config.mapping
        x, y = self.get_param("goal_x", 8), self.get_param("goal_y", 6)
        if not (m.origin[0] <= x < m.origin[0] + m.width*m.resolution and m.origin[1] <= y < m.origin[1] + m.height*m.resolution):
            raise ValueError("Navigation goal is outside the configured occupancy map")
        points = self.get_param("waypoints", [])
        if not isinstance(points, list) or len(points) > 100:
            raise ValueError("Waypoints must be a list of at most 100 [x, y] coordinates")
        for point in points:
            if not isinstance(point, list) or len(point) != 2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in point):
                raise ValueError("Each waypoint must contain two finite coordinates")
            x,y = point
            if not (m.origin[0] <= x < m.origin[0]+m.width*m.resolution and m.origin[1] <= y < m.origin[1]+m.height*m.resolution):
                raise ValueError(f"Waypoint {point} is outside the map")

    def on_start(self):
        self.path, self.last_plan, self.goal = [], -100.0, None
        self.waypoint_index = 0
        self._mission_complete = False
        self._last_sensor_time = None
        self._last_received = time.monotonic()
        self._last_status = None
        self._timed_out = False
        self._last_command = None
        self._command_source = None
        self.start_worker()

    def process(self, port, payload):
        with self._control_lock:
            now = float(payload["time"])
            if not math.isfinite(now) or (self._last_sensor_time is not None and now <= self._last_sensor_time):
                return
            self._last_sensor_time = now
            self._last_received = time.monotonic()
            self._timed_out = False
            self._process_observation(payload)

    def _process_observation(self, payload):
        goal = [self.get_param("goal_x", 8.0), self.get_param("goal_y", 6.0)]
        waypoints = self.get_param("waypoints", [])
        if waypoints:
            goal = waypoints[min(self.waypoint_index, len(waypoints)-1)]
        pose, now = payload["pose"], payload["time"]
        if goal != self.goal or now-self.last_plan >= 1.0 or not self.path:
            self.path = plan_path(payload["grid"], payload["origin"], payload["resolution"], pose, goal, radius=self.robot_config.mapping.inflation_radius)
            self.last_plan, self.goal = now, goal
        linear, angular, status = follow_path(pose, self.path, goal, payload["scan"], self.get_param("max_speed", .65),
            stop_distance=self.robot_config.drive.collision_radius + .07)
        if not self.get_param("enabled", True):
            linear = angular = 0.0
            status = "paused"
        elif status == "goal_reached" and waypoints:
            if self.waypoint_index < len(waypoints)-1:
                self.waypoint_index += 1
                self.path = []
            else:
                status = "mission_complete"
                self._mission_complete = True
        if waypoints and self._mission_complete and self.get_param("enabled", True):
            linear = angular = 0.
            status = "mission_complete"
        self._last_command = {"linear": linear, "angular": angular, "time": now, "frame": self.robot_config.drive.base_frame}
        self._command_source = getattr(self._context, "message", None)
        self.emit("cmd_vel", self._last_command)
        self._last_status = {"points": self.path, "goal": goal, "status": status,
            "distance_to_goal": math.dist(pose[:2], goal), "time": now, "pose": pose,
            "waypoints": waypoints, "waypoint_index": self.waypoint_index}
        self.emit("path", self._last_status)

    def _emit_stop(self, status):
        self._last_command = None
        self.emit("cmd_vel", {"linear": 0.0, "angular": 0.0, "time": self._last_sensor_time or 0.0, "frame": self.robot_config.drive.base_frame})
        report = dict(self._last_status or {"points": [],
            "goal": [self.get_param("goal_x", 8.0), self.get_param("goal_y", 6.0)],
            "time": 0.0, "pose": None, "distance_to_goal": None})
        report.update(status=status, points=[])
        self.emit("path", report)

    def on_tick(self):
        with self._control_lock:
            if not self._timed_out and time.monotonic()-self._last_received >= self.SENSOR_TIMEOUT:
                self._timed_out = True
                self.path = []
                self._emit_stop("sensor_timeout")
            elif not self._timed_out and self._last_command and self.get_param("enabled", True):
                # Keep the command selector fed between map updates. This never
                # refreshes the sensor watchdog or changes capture provenance.
                with self.processing(self._command_source):
                    self.emit("cmd_vel", self._last_command)

    def on_params_changed(self, updated):
        with self._control_lock:
            self.validate_configuration()
            if "waypoints" in updated:
                self.waypoint_index, self.path, self.goal = 0, [], None
                self._mission_complete = False
            if not self.get_param("enabled", True):
                self._emit_stop("paused")
