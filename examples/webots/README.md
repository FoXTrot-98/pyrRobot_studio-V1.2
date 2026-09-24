# Existing Webots robots in Studio

Start Studio's backend and frontend normally. In Studio choose **Examples**, open a robot, then **Start Graph**. Webots opens its original 3D world; Studio displays action buttons and Rerun joint telemetry. Stop Graph closes the Webots process Studio started. Save project exports your graph and settings.

| Example | Controls | Reused Webots world |
| --- | --- | --- |
| Panda arm | Reach near/far, open/close gripper, hold | `franka_emika/panda/worlds/panda.wbt` |
| NAO humanoid | Wave, wipe forehead, hold; camera stream | `softbank/nao/worlds/nao_demo.wbt` |
| KUKA youBot | Arm home/front, gripper, hold; enable Manual driving and focus the keyboard pad for WASD/arrows | `kuka/youbot/worlds/youbot.wbt` |

Alternatively, use **Open project** with one of the JSON files in this directory. No URDF upload or Robot setup wizard is needed: these examples use native Webots PROTO models, including their existing meshes, joints and physics. The current setup wizard remains for the four-wheel reference robot.

Install Webots R2025a with its sample projects. Studio detects the installation; if necessary select the robot node and set `executable` before starting. First launch needs internet access for Webots' official PROTO/mesh downloads. Allow up to three minutes. Connection failures include a path to `artifacts/webots-examples/<run>/webots.log`. The source installation is never edited: Studio copies the world and replaces its controller fields. Exported projects refer to the installed assets; they do not bundle Webots or its asset cache.

Every run starts holding, regardless of the saved action. Select an action after starting. Hold stops the active motion and requests joint holding; sensorless motors are stopped with zero velocity. This is simulation control, not a certified emergency stop. Keyboard commands expire after 350 ms; releasing keys, leaving the pad, or disconnecting the keyboard stops manual driving. Stop the graph before changing profile or executable.

For custom node control, connect `pyrobot/JointTargets@1` to `targets`: `{"frame":"robot","positions":{"panda_joint2":0.37}}`. Positions use radians for rotational joints and metres for linear joints. The controller validates every requested motor and limit before applying any target. Wheel motors use the youBot `cmd_vel` input instead. State messages include joint names and units, simulation capture time, status and rejected-command errors. Only joints with available, finite position-sensor readings appear in telemetry.

These are starting examples, not complete autonomy stacks. NAO provides upper-body motions, not walking or balance control. Arm presets are joint targets, not collision-aware planning or inverse kinematics. The stock youBot example has no lidar SLAM/navigation pipeline. Rerun displays telemetry and available camera images; the original robot's full 3D model remains in Webots.

## Validation

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe tests/run_all.py
.\.venv\Scripts\python.exe tests/webots_examples_smoke.py
```

The second command launches each real simulator example and checks joint movement, holding, telemetry, NAO camera, youBot base driving/stopping and owned-process cleanup. It requires Webots and its assets.

## Upstream assets and attribution

Worlds, PROTOs, meshes and NAO motion files come from [Cyberbotics Webots R2025a](https://github.com/cyberbotics/webots/tree/R2025a/projects/robots). Their upstream licenses and notices apply; these assets are not relicensed by Studio. Generated runs record the original world path in `SOURCE.txt`. Panda and youBot pose values follow their bundled demonstration controllers; NAO motions are copied unchanged from its installed `motions` directory.
