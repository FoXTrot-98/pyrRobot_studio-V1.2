# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Geometry clearance and sensor baseline regressions."""
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from core.simulation.config import RobotConfiguration, PhysicsSettings
from core.simulation.mesh_robot import required_clearance, validate_simulation_model
from core.simulation.navigation import WheelOdometry
from core.urdf.model import load_urdf
from core.runtime.robot_setup import inspect_robot
from plugins.user.four_wheel_sim import FourWheelSimulation
from plugins.user.webots_sim import WebotsSimulation


class PhysicsTests(unittest.TestCase):
    def test_legacy_defaults_and_custom_roundtrip(self):
        legacy=RobotConfiguration.model_validate({})
        self.assertEqual(legacy.physics.body_mass,8)
        self.assertEqual(legacy.physics.wheel_friction,.8)
        custom=RobotConfiguration(physics={'body_mass':17,'wheel_friction':.61})
        self.assertEqual(RobotConfiguration.model_validate_json(custom.model_dump_json()),custom)

    def test_invalid_physics_rejected(self):
        from pydantic import ValidationError
        for name in PhysicsSettings.model_fields:
            for value in (-1,float('nan'),float('inf')):
                with self.subTest(name=name,value=value),self.assertRaises(ValidationError):
                    PhysicsSettings(**{name:value})
        for name in ('body_mass','wheel_mass','motor_max_torque','motor_max_velocity'):
            with self.assertRaises(ValidationError):PhysicsSettings(**{name:0})


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.model=load_urdf(ROOT/'examples/four-wheel/robot.urdf')
        self.config=RobotConfiguration()

    def test_body_and_outboard_wheels_require_actual_clearance(self):
        minimum=required_clearance(self.model,self.config)
        self.assertGreater(minimum,.48)
        validate_simulation_model(self.model,self.config)
        self.config.drive.collision_radius=.01
        for node_type in (FourWheelSimulation,WebotsSimulation):
            node=node_type(node_id='sim',bus=Mock(),urdf_link='base_link')
            node.robot_model=self.model;node.robot_config=self.config
            with self.assertRaisesRegex(ValueError,'clearance radius must be at least'):
                node.validate_configuration()

    def test_offset_body_and_larger_robot_get_larger_suggested_clearance(self):
        self.model.links['base_link'].visual_origin.xyz=(1.,0.,.25)
        self.assertGreater(required_clearance(self.model,self.config),1.3)
        xml=(ROOT/'examples/four-wheel/robot.urdf').read_text().replace('.72 .48 .22','2 .48 .22')
        suggested=inspect_robot(xml)['suggested_config']
        self.assertGreater(suggested['drive']['collision_radius'],1.)
        self.assertGreaterEqual(suggested['mapping']['inflation_radius'],suggested['drive']['collision_radius'])


class EncoderBaselineTests(unittest.TestCase):
    def test_nonzero_counts_start_at_rest_then_integrate_deltas(self):
        odometry=WheelOdometry()
        np.testing.assert_allclose(odometry.update([4096]*4,.12,.62),[0,0,0])
        np.testing.assert_allclose(odometry.update([4096+1024]*4,.12,.62),[math.pi*.12/2,0,0])

    def test_initial_gyro_heading_is_relative_and_restart_rebaselines(self):
        for initial in ([4096]*4,[-8192]*4):
            odometry=WheelOdometry()
            np.testing.assert_allclose(odometry.update(initial,.12,.62,gyro_yaw=2.),[0,0,0])
            self.assertAlmostEqual(odometry.relative_gyro(2.),0)
            self.assertAlmostEqual(odometry.update(initial,.12,.62,gyro_yaw=2.2)[2],.2)
            self.assertAlmostEqual(odometry.relative_gyro(2.2),.2)


if __name__=='__main__':unittest.main()
