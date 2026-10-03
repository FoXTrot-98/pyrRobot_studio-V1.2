# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

import math
import threading
import time
import uuid
from sdk.pyrobot_plugin import PluginManifest, PortSpec, PortDataType as T, ParamSpec
from core.simulation.worker import WorkerNode
from core.simulation.navigation import plan_path, follow_path, no_path_reason
from core.simulation.world import wrap
from core.simulation.exploration import frontier_goal, exploration_path


class AStarNavigation(WorkerNode):
    SENSOR_TIMEOUT = 1.5

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._control_lock = threading.RLock()
        self._last_sensor_time = self._last_status = None
        self.replans = 0
        self._home_pose = self._latest_pose = None
        self._home_reached = False
        self._reset_exploration()
        self._new_mission()

    manifest = PluginManifest(id="pyrobot.navigation.astar", name="A* navigation", category="Navigation",
        description="A* or Dijkstra planning with proportional or fuzzy path following, measured occupancy, inflated obstacles and a front lidar stop.",
        inputs=[PortSpec("state", T.JSON, schema="pyrobot/MappingState@1")], outputs=[PortSpec("cmd_vel", T.JSON, schema="pyrobot/VelocityCommand@1"), PortSpec("path", T.JSON, schema="pyrobot/NavigationPath@1")],
        params=[ParamSpec("planner", "enum", default="astar", options=["astar", "dijkstra"]),
                ParamSpec("controller", "enum", default="proportional", options=["proportional", "fuzzy"]),
                ParamSpec("goal_x", "number", default=8.0),
                ParamSpec("goal_y", "number", default=6.0),
                ParamSpec("max_speed", "number", default=.65, min=.1, max=.8),
                ParamSpec("waypoints", "json", default=[], description="Ordered map coordinates in metres, configured by clicking the SLAM map."),
                ParamSpec("blocked_timeout", "number", default=8., min=1., max=120., description="Seconds to retry a blocked route before stopping for operator action."),
                ParamSpec("progress_timeout", "number", default=12., min=1., max=120., description="Seconds without translation or commanded turn progress before declaring navigation stalled."),
                ParamSpec("home_pose", "json", default=[], description="Map-frame [x, y, yaw] home pose. Empty captures the first pose of each run."),
                ParamSpec("return_home", "bool", default=False, description="Return to home instead of following the waypoint mission."),
                ParamSpec("explore", "bool", default=False, description="Explore reachable measured frontiers, then return home."),
                ParamSpec("exploration_targets", "number", default=20, min=1, max=100, description="Maximum frontier targets per exploration run."),
                ParamSpec("cancel_mission", "bool", default=False, description="Latch a mission cancellation until an explicit new mission is requested."),
                ParamSpec("enabled", "bool", default=True)])

    def validate_configuration(self):
        if self.get_param("planner", "astar") not in ("astar", "dijkstra") or self.get_param("controller", "proportional") not in ("proportional", "fuzzy"):
            raise ValueError("Unsupported navigation planner or controller")
        m = self.robot_config.mapping
        x, y = self.get_param("goal_x", 8), self.get_param("goal_y", 6)
        if not (m.origin[0] <= x < m.origin[0] + m.width*m.resolution and m.origin[1] <= y < m.origin[1] + m.height*m.resolution):
            raise ValueError("Navigation goal is outside the configured occupancy map")
        home = self.get_param("home_pose", [])
        if not isinstance(home, list) or len(home) not in (0,3) or any(type(v) not in (int,float) or not math.isfinite(v) for v in home):
            raise ValueError("Home pose must be empty or three finite map coordinates [x, y, yaw]")
        if home and not (m.origin[0] <= home[0] < m.origin[0]+m.width*m.resolution and m.origin[1] <= home[1] < m.origin[1]+m.height*m.resolution):
            raise ValueError("Home pose is outside the configured occupancy map")
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
        configured_home = self.get_param("home_pose", [])
        self._home_pose = list(configured_home) if configured_home else None
        self._latest_pose = None
        self._home_reached = False
        self._reset_exploration()
        self._new_mission()
        self.path, self.last_plan, self.goal = [], -100.0, None
        self.waypoint_index = 0
        self._mission_complete = False
        self._last_sensor_time = None
        self._last_received = time.monotonic()
        self._last_status = None
        self._timed_out = False
        self._last_command = None
        self._command_source = None
        self.replans = 0
        self._reset_recovery()
        self.start_worker()

    def _new_mission(self):
        self._mission_id = uuid.uuid4().hex
        self._goal_complete = False

    def _mission_report(self, report):
        kind = "return_home" if self.get_param("return_home", False) else "exploration" if self.get_param("explore", False) else "waypoints" if self.get_param("waypoints", []) else "goal"
        status = report["status"]
        if self.get_param("cancel_mission", False):
            state, recovery = "cancelled", "start_new"
        elif getattr(self, "_failure", None):
            state, recovery = "failed", "retry_or_cancel"
        elif status in ("home_reached", "mission_complete") or self._goal_complete or (kind in ("return_home", "exploration") and self._home_reached) or (kind == "waypoints" and getattr(self,"_mission_complete",False)):
            state, recovery = "completed", "start_new"
        elif status == "paused":
            state, recovery = "paused", "resume_or_cancel"
        elif status == "sensor_timeout":
            state, recovery = "waiting_for_sensors", "wait_for_sensors"
        elif status in ("no_path", "obstacle_stop", "replanning"):
            state, recovery = "recovering", "automatic_replan"
        else:
            state, recovery = "running", "none"
        report.update(planner=self.get_param("planner", "astar"), controller=self.get_param("controller", "proportional"), mission_id=self._mission_id, mission_type=kind, mission_state=state, recovery_action=recovery)

    def _reset_exploration(self):
        self._frontier = None
        self._visited = []
        self._exploration_return = False
        self._exploration_reason = None

    def _reset_recovery(self, clear_failure=True):
        self._blocked_since = None
        self._progress_since = None
        self._progress_pose = None
        if clear_failure:
            self._failure = None

    def process(self, port, payload):
        with self._control_lock:
            now = float(payload["time"])
            if not math.isfinite(now) or (self._last_sensor_time is not None and now <= self._last_sensor_time):
                return
            self._latest_pose = list(payload["pose"])
            if self._home_pose is None:
                self._home_pose = list(payload["pose"])
            self._last_sensor_time = now
            self._last_received = time.monotonic()
            if self._timed_out:
                self.path, self.goal = [], None
                self._reset_recovery(clear_failure=False)
            self._timed_out = False
            self._process_observation(payload)

    def _process_observation(self, payload):
        if self.get_param("cancel_mission", False):
            self._emit_stop("cancelled", "Mission cancelled. Start a new mission to move again.")
            return
        goal = [self.get_param("goal_x", 8.0), self.get_param("goal_y", 6.0)]
        waypoints = self.get_param("waypoints", [])
        if waypoints:
            goal = waypoints[min(self.waypoint_index, len(waypoints)-1)]
        exploring = self.get_param("explore", False) and not self.get_param("return_home", False)
        if exploring and not self._exploration_return and self.get_param("enabled", True) and not self._failure:
            if self._frontier is not None and math.dist(payload["pose"][:2], self._frontier) < .25:
                self._frontier = None
            if self._frontier is None:
                if len(self._visited) < self.get_param("exploration_targets", 20):
                    self._frontier = frontier_goal(payload["grid"], payload["origin"], payload["resolution"],
                        payload["pose"], self.robot_config.mapping.inflation_radius, self._visited)
                if self._frontier is None:
                    # Lack of a usable start pose is not exploration completion.
                    start_reason = no_path_reason(payload["grid"], payload["origin"], payload["resolution"],
                        payload["pose"], payload["pose"][:2], self.robot_config.mapping.inflation_radius)
                    sx, sy = [math.floor((payload["pose"][i]-payload["origin"][i])/payload["resolution"]) for i in (0,1)]
                    if (0 <= sy < len(payload["grid"]) and 0 <= sx < len(payload["grid"][sy])
                            and payload["grid"][sy][sx] < 0):
                        start_reason = "Robot pose is not in measured free space. Wait for map coverage, then retry exploration."
                    if len(self._visited) < self.get_param("exploration_targets",20) and start_reason.startswith("Robot"):
                        self._failure = ("navigation_failed", start_reason)
                        self._emit_stop(*self._failure)
                        return
                    self._exploration_return = True
                    self._exploration_reason = "Target limit reached" if len(self._visited) >= self.get_param("exploration_targets",20) else "No remaining reachable frontiers"
                else:
                    self._visited.append(self._frontier)
        if exploring and self._frontier is not None:
            goal, waypoints = self._frontier, []
        returning = self.get_param("return_home", False) or (exploring and self._exploration_return)
        if returning:
            goal, waypoints = list(self._home_pose[:2]), []
        pose, now = payload["pose"], payload["time"]
        if self._failure and self.get_param("enabled", True):
            self._emit_stop(*self._failure)
            return
        if goal != self.goal:
            self._reset_recovery()
        if goal != self.goal or now-self.last_plan >= 1.0:
            if exploring and not returning:
                # Preserve physical obstacle clearance and prohibit unknown shortcuts.
                self.path = exploration_path(payload, pose, goal, self.robot_config.mapping.inflation_radius, algorithm=self.get_param("planner", "astar"))
            else:
                self.path = plan_path(payload["grid"], payload["origin"], payload["resolution"], pose, goal, radius=self.robot_config.mapping.inflation_radius, algorithm=self.get_param("planner", "astar"))
            self.last_plan, self.goal = now, goal
            self.replans += 1
        linear, angular, status = follow_path(pose, self.path, goal, payload["scan"], self.get_param("max_speed", .65),
            stop_distance=self.robot_config.drive.collision_radius + .07, controller=self.get_param("controller", "proportional"),
            map_state=payload, radius=self.robot_config.mapping.inflation_radius)
        if returning and (status == "goal_reached" or self._home_reached):
            heading_error = wrap(self._home_pose[2] - pose[2])
            linear = 0.0
            if self._home_reached or abs(heading_error) <= .1:
                angular, status = 0.0, "home_reached"
                if self.get_param("enabled", True):
                    self._home_reached = True
            else:
                angular, status = max(-.8,min(.8,2.4*heading_error)), "aligning_home"
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
        if not exploring and not returning and not waypoints and self.get_param("enabled", True):
            if status == "goal_reached":
                self._goal_complete = True
            if self._goal_complete:
                linear = angular = 0.
                status = "goal_reached"
        if returning and status == "navigating":
            status = "returning_home"
        route_reason = no_path_reason(payload["grid"],payload["origin"],payload["resolution"],pose,goal,self.robot_config.mapping.inflation_radius) if status == "no_path" else None
        if exploring and not returning and status == "no_path" and route_reason.startswith("Goal"):
            # New scans can invalidate a previously safe frontier. Waiting the
            # entire obstacle timeout cannot make that target useful again.
            self._frontier = None
            self.path, self.goal = [], None
            self._reset_recovery()
            self._emit_stop("replanning", "New map data blocked the frontier; selecting another target")
            return
        # Recovery uses monotonic elapsed time, independent of simulation speed.
        wall_now = time.monotonic()
        if status in ("paused", "goal_reached", "mission_complete", "home_reached"):
            self._reset_recovery()
        elif status in ("no_path", "obstacle_stop"):
            linear = angular = 0.0
            # Waiting with zero command is not failed drive progress. Pause
            # that budget, but retain prior unproductive driving time so
            # alternating blocked/clear observations cannot reset it forever.
            if self._blocked_since is None:
                self._blocked_since = wall_now
            if wall_now - self._blocked_since >= self.get_param("blocked_timeout", 8.):
                self._failure = ("navigation_failed", route_reason or "An obstacle remained too close. Clear the obstruction or choose another goal, then retry.")
        else:
            if self._blocked_since is not None and self._progress_since is not None:
                self._progress_since += wall_now-self._blocked_since
            self._blocked_since = None
        if not self._failure and status not in ("paused", "goal_reached", "mission_complete", "home_reached", "no_path", "obstacle_stop"):
            turn_progress = (self._progress_pose is not None and abs(angular) > .05
                             and abs(wrap(pose[2]-self._progress_pose[2])) >= .15)
            if self._progress_pose is None or math.dist(pose[:2], self._progress_pose[:2]) >= .08 or turn_progress:
                self._progress_pose, self._progress_since = list(pose), wall_now
            elif wall_now - self._progress_since >= self.get_param("progress_timeout", 12.):
                self._failure = ("stalled", "No translation or commanded turn progress within the timeout. Check the drive and localization, then retry.")
        if self._failure and self._failure[0] == "navigation_failed" and exploring and not returning:
            self._frontier = None
            self._reset_recovery()
            self.path, self.goal = [], None
            self._emit_stop("replanning", "Skipping blocked frontier")
            return
        if self._failure:
            self.path = []
            self._emit_stop(*self._failure)
            return
        self._last_command = {"linear": linear, "angular": angular, "time": now, "frame": self.robot_config.drive.base_frame}
        self._command_source = getattr(self._context, "message", None)
        self.emit("cmd_vel", self._last_command)
        self._last_status = {"points": self.path, "goal": goal, "status": status,
            "distance_to_goal": math.dist(pose[:2], goal), "time": now, "pose": pose,
            "waypoints": waypoints, "waypoint_index": self.waypoint_index, "replans": self.replans, "reason": route_reason or (self._exploration_reason if exploring else None), "exploration_targets": len(self._visited), "exploring": exploring, "home_pose": self._home_pose, "returning_home": returning}
        self._mission_report(self._last_status)
        self.emit("path", self._last_status)

    def _emit_stop(self, status, reason=None):
        self._last_command = None
        self.emit("cmd_vel", {"linear": 0.0, "angular": 0.0, "time": self._last_sensor_time or 0.0, "frame": self.robot_config.drive.base_frame})
        report = dict(self._last_status or {"points": [],
            "goal": [self.get_param("goal_x", 8.0), self.get_param("goal_y", 6.0)],
            "time": 0.0, "pose": None, "distance_to_goal": None})
        returning = self.get_param("return_home", False) or (self.get_param("explore", False) and getattr(self,"_exploration_return",False))
        report.update(status=status, points=[], reason=reason, replans=self.replans,
                      home_pose=self._home_pose, returning_home=returning,
                      exploring=self.get_param("explore",False) and not self.get_param("return_home",False),
                      exploration_targets=len(self._visited),
                      pose=self._latest_pose, time=self._last_sensor_time or 0.0)
        if returning and self._home_pose:
            report.update(goal=self._home_pose[:2], waypoints=[], waypoint_index=0)
            if self._latest_pose:
                report['distance_to_goal'] = math.dist(self._latest_pose[:2],self._home_pose[:2])
        self._mission_report(report)
        self._last_status = report
        self.emit("path", report)

    def on_tick(self):
        with self._control_lock:
            if self.get_param("cancel_mission", False):
                return
            if not self._timed_out and time.monotonic()-self._last_received >= self.SENSOR_TIMEOUT:
                self._timed_out = True
                self.path = []
                self._emit_stop("sensor_timeout")
            elif not self._timed_out and self._last_command and self.get_param("enabled", True):
                # Keep the command selector fed between map updates. This never
                # refreshes the sensor watchdog or changes capture provenance.
                with self.processing(self._command_source):
                    self.emit("cmd_vel", self._last_command)

    def update_params(self, updates):
        # A worker must never see new mission parameters with the old route.
        with self._control_lock:
            super().update_params(updates)

    def on_params_changed(self, updated):
        with self._control_lock:
            self.validate_configuration()
            new_mission = bool({"waypoints", "goal_x", "goal_y", "home_pose", "return_home", "explore"} & updated.keys())
            if new_mission:
                if "cancel_mission" not in updated:
                    self.params["cancel_mission"] = False
                self._new_mission()
            if self.get_param("cancel_mission", False):
                self.path, self.goal = [], None
                self._reset_recovery()
                self._emit_stop("cancelled", "Mission cancelled. Start a new mission to move again.")
                return
            if {"waypoints", "goal_x", "goal_y"} & updated.keys():
                self.waypoint_index, self.path, self.goal = 0, [], None
                self._mission_complete = False
            if "home_pose" in updated:
                self._home_pose = list(self.get_param("home_pose", [])) or None
            if {"explore", "home_pose", "return_home", "waypoints", "goal_x", "goal_y"} & updated.keys():
                self._reset_exploration()
            if {"explore", "home_pose", "return_home"} & updated.keys():
                self._home_reached = False
            if {"waypoints", "goal_x", "goal_y", "enabled", "home_pose", "return_home", "explore", "exploration_targets", "cancel_mission", "planner", "controller"} & updated.keys():
                algorithm_only = set(updated) <= {"planner", "controller"}
                self._reset_recovery(clear_failure=not algorithm_only)
                self.path, self.goal = [], None
                # Discard the old heartbeat before awaiting the next observation.
                self._emit_stop("replanning" if self.get_param("enabled", True) else "paused")
