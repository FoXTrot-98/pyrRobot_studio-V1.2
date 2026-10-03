# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Shared approximate skid-steer contact model for generated/imported worlds.

These defaults permit lateral tire slip while turning. They are not measured
tire properties; keep both world generators on this same contact model.
"""
import json

WHEEL_FRICTION = 0.8
WHEEL_FORCE_DEPENDENT_SLIP = 0.02


def wheel_contact_properties(wheel_material, surface_material, physics=None):
    friction = WHEEL_FRICTION if physics is None else physics.wheel_friction
    slip = WHEEL_FORCE_DEPENDENT_SLIP if physics is None else physics.wheel_slip
    return (f'ContactProperties {{ material1 {json.dumps(wheel_material)} '
            f'material2 {json.dumps(surface_material)} '
            f'coulombFriction [ {friction:g} ] '
            f'forceDependentSlip [ {slip:g} ] }}')
