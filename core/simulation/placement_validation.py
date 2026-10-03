# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Placement policy shared by the live controller and placement preview.

The current profile requires four supported wheels on a level floor. These
named tolerances are in SI units and describe validation, not tire physics.
"""
import math

SETTLE_SECONDS = 2.0
STARTUP_TIMEOUT_SECONDS = 8.0
STABLE_SECONDS = 0.5
MAX_LINEAR_SPEED = 0.02
MAX_ANGULAR_SPEED = 0.05
MAX_TILT_RADIANS = math.radians(10)
MAX_PLANAR_DRIFT = 0.02
MAX_HEIGHT_DRIFT = 0.03
MAX_HEADING_DRIFT = math.radians(3)


class PlacementCheck:
    def __init__(self, config):
        self.config = config
        self.stable_since = None
        self.physical_since = None

    def update(self, time, position, orientation, velocity, body_contact,
               supported_wheels, sensors_ready):
        reasons = []
        target = self.config['spawn_pose']
        yaw = math.atan2(orientation[3], orientation[0])
        if not all(math.isfinite(v) for v in [*position, *orientation, *velocity]):
            reasons.append('Invalid physics state')
        if body_contact:
            reasons.append('Robot body or wheel side touches the environment; move to a clear position')
        if supported_wheels != 4:
            reasons.append(f'Floor supports {supported_wheels}/4 wheels; choose a level floor and correct height')
        if orientation[8] < math.cos(MAX_TILT_RADIANS):
            reasons.append('Robot is tilted; this drive profile requires a level floor')
        if (math.sqrt(sum(v*v for v in velocity[:3])) > MAX_LINEAR_SPEED or
                math.sqrt(sum(v*v for v in velocity[3:])) > MAX_ANGULAR_SPEED):
            reasons.append('Robot is still moving or falling')
        if not sensors_ready:
            reasons.append('Waiting for valid lidar, camera, encoders and gyro')
        if reasons:
            self.physical_since = None
        elif self.physical_since is None:
            self.physical_since = time
        can_use_observed = (time >= SETTLE_SECONDS and self.physical_since is not None
                            and time-self.physical_since >= STABLE_SECONDS)
        if math.hypot(position[0]-target[0], position[1]-target[1]) > MAX_PLANAR_DRIFT:
            reasons.append('Observed X/Y differs from Studio; use the Webots position or edit the spawn')
        if abs(position[2]-self.config.get('spawn_height', .002)) > MAX_HEIGHT_DRIFT:
            reasons.append('Floor height differs from Studio; use the Webots position once safely settled')
        if abs(math.atan2(math.sin(yaw-target[2]), math.cos(yaw-target[2]))) > MAX_HEADING_DRIFT:
            reasons.append('Observed heading differs from Studio; use the Webots position or edit the heading')
        if reasons:
            self.stable_since = None
        elif self.stable_since is None:
            self.stable_since = time
        stable = self.stable_since is not None and time-self.stable_since >= STABLE_SECONDS
        status = 'checking' if time < SETTLE_SECONDS else 'valid' if stable else 'invalid'
        if not reasons and not stable:
            reasons.append('Waiting for a stable resting position')
        return dict(status=status, reasons=reasons, observed_position=list(position), observed_yaw=yaw,
                    can_use_observed=can_use_observed)
