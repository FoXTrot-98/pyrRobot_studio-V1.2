# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from plugins.processing.pointcloud_filter import voxel_downsample


def test_voxel_downsample_merges_nearby_points():
    points = np.array([
        [0.01, 0.01, 0.01],
        [0.02, 0.03, 0.01],
        [0.05, 0.02, 0.04],
        [1.01, 1.02, 1.00],
        [1.03, 1.01, 1.02],
    ])
    result = voxel_downsample(points, voxel_size=0.5)
    assert len(result) == 2, f"expected 2 voxel centroids, got {len(result)}"
    print(f"OK: 5 points in 2 clusters -> {len(result)} voxel centroids")

    near_origin = [c for c in result if np.linalg.norm(c) < 0.5]
    near_one = [c for c in result if np.linalg.norm(c - [1, 1, 1]) < 0.5]
    assert len(near_origin) == 1 and len(near_one) == 1
    expected_origin_centroid = points[:3].mean(axis=0)
    assert np.allclose(near_origin[0], expected_origin_centroid, atol=1e-9)
    print(f"OK: origin-cluster centroid exactly matches the mean of its 3 input points: {near_origin[0]}")


def test_voxel_downsample_empty_input():
    result = voxel_downsample(np.zeros((0, 3)), voxel_size=0.1)
    assert len(result) == 0
    print("OK: empty point cloud in -> empty point cloud out, no crash")


def test_voxel_downsample_no_merging_when_points_are_far_apart():
    points = np.array([[0, 0, 0], [10, 10, 10], [-10, -10, -10]])
    result = voxel_downsample(points, voxel_size=0.1)
    assert len(result) == 3
    print("OK: 3 far-apart points with a small voxel size -> no merging (3 in, 3 out)")


if __name__ == "__main__":
    test_voxel_downsample_merges_nearby_points()
    test_voxel_downsample_empty_input()
    test_voxel_downsample_no_merging_when_points_are_far_apart()
    print("\nAll point cloud filter tests passed.")
