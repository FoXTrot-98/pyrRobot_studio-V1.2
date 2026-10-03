# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Bounded, geometry-scaled placement suggestions and acceptance guards."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.simulation.config import RobotConfiguration
from core.simulation.placement_search import PlacementSearch, candidates
from core.simulation.placement_preview import PlacementPreview


class SearchTests(unittest.TestCase):
    def config(self):
        config=RobotConfiguration().model_dump()
        config['mapping'].update(origin=[-15,-15],width=200,height=200,resolution=.15)
        return config

    def test_candidates_use_selected_pose_geometry_and_mapping_bounds(self):
        config=self.config();config['spawn_pose']=[4,2,.3]
        points=candidates(config)
        self.assertEqual(len(points),25)
        self.assertEqual(points[0],[4,2,.002,.3])
        self.assertAlmostEqual(abs(points[1][0]-4),2*config['drive']['collision_radius'])
        config['mapping'].update(origin=[3,1],width=2,height=2,resolution=1)
        self.assertEqual(len(candidates(config)),1)
        config['mapping'].update(width=1,height=1)
        self.assertEqual(candidates(config),[])

    def test_search_is_bounded_and_can_be_cancelled(self):
        search=PlacementSearch(self.config())
        self.assertIsNotNone(search.start(10))
        for i in range(25):search.update(10+(i+1)*3,{'can_use_observed':False})
        self.assertEqual(search.status,'exhausted')
        self.assertEqual(search.report()['attempt'],25)
        search.start(100);search.cancel()
        self.assertIsNone(search.update(104,{'can_use_observed':False}))
        self.assertEqual(search.status,'cancelled')

    def test_only_physically_settled_in_bounds_position_can_be_suggested(self):
        search=PlacementSearch(self.config());search.start(0)
        search.update(2,dict(can_use_observed=True,observed_position=[30,30,0]))
        self.assertEqual(search.status,'searching')
        search.update(2.1,dict(can_use_observed=True,observed_position=[0,0,0]))
        self.assertEqual(search.status,'found')
        preview=PlacementPreview.__new__(PlacementPreview);preview.searched=True
        with self.assertRaisesRegex(ValueError,'check it again'):
            preview.require_valid(None)


if __name__=='__main__':unittest.main()
