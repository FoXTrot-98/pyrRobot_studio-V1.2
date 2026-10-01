# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.urdf.model import load_urdf

FIXTURE = Path(__file__).parent / "fixtures" / "sample_robot.urdf"


def test_load_and_link_names():
    model = load_urdf(FIXTURE)
    assert model.name == "sample_bot"
    assert set(model.link_names()) == {"base_link", "lidar_link", "wheel_left_link"}
    print(f"OK: parsed robot '{model.name}' with links {model.link_names()}")


def test_joint_parsing():
    model = load_urdf(FIXTURE)
    lidar_joint = model.parent_joint_of("lidar_link")
    assert lidar_joint is not None
    assert lidar_joint.joint_type == "fixed"
    assert lidar_joint.origin.xyz == (0.1, 0.0, 0.25)
    print(f"OK: lidar_link mounted via '{lidar_joint.name}' at offset {lidar_joint.origin.xyz}")

    wheel_joint = model.parent_joint_of("wheel_left_link")
    assert wheel_joint.joint_type == "continuous"
    assert wheel_joint.limit_effort == 10.0
    print(f"OK: wheel joint is continuous with effort limit {wheel_joint.limit_effort}")


def test_kinematic_chain():
    model = load_urdf(FIXTURE)
    chain = model.path_to_root("lidar_link")
    assert [j.name for j in chain] == ["base_to_lidar"]
    print(f"OK: path_to_root('lidar_link') = {[j.name for j in chain]}")

    root_chain = model.path_to_root("base_link")
    assert root_chain == []
    print("OK: base_link (root) has empty path_to_root")


def test_static_transform_only_for_fixed_joints():
    model = load_urdf(FIXTURE)
    lidar_tf = model.static_transform("base_link", "lidar_link")
    assert lidar_tf is not None
    print(f"OK: static_transform(base_link, lidar_link) resolved: {lidar_tf}")

    wheel_tf = model.static_transform("base_link", "wheel_left_link")
    assert wheel_tf is None  # continuous joint -> not a static offset
    print("OK: static_transform correctly refuses a path through a non-fixed joint")


if __name__ == "__main__":
    test_load_and_link_names()
    test_joint_parsing()
    test_kinematic_chain()
    test_static_transform_only_for_fixed_joints()
    print("\nAll URDF tests passed.")
