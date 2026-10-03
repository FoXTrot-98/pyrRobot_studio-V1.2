# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Copied into generated Webots projects; only uses stdlib and Webots API."""
import base64
import json
import math
from pathlib import Path
import socket
import sys
import time


def lidar_angles(width, field_of_view):
    # Fixed cylindrical lidar samples pixel centres, not both FOV endpoints.
    return [field_of_view/2 - (i+.5)*field_of_view/width for i in range(width)]


def main():
    from controller import Supervisor
    from placement_validation import PlacementCheck, STARTUP_TIMEOUT_SECONDS
    from placement_search import PlacementSearch
    robot = Supervisor()
    info = json.loads((Path(__file__).parent/"robot.json").read_text())
    config, joints = info["config"], info["joints"]
    placement = PlacementCheck(config)
    preview = info.get('placement_preview', False)
    ready = False
    search = PlacementSearch(config) if preview else None
    placement_started = 0.

    def move_probe(point, now):
        nonlocal placement, placement_started
        robot.getSelf().getField('translation').setSFVec3f(point[:3])
        robot.getSelf().getField('rotation').setSFRotation([0.,0.,1.,point[3]])
        robot.getSelf().resetPhysics()
        placement = PlacementCheck(config)
        placement_started = now
    wheel_nodes = [robot.getFromDef(f'PYROBOT_WHEEL_{i}') for i in range(4)]
    motors = [robot.getDevice(name) for name in joints]
    encoders = [robot.getDevice(name+"_encoder") for name in joints]
    for motor in motors:
        motor.setPosition(float("inf"))
        motor.setVelocity(0.)
    for encoder in encoders:
        encoder.enable(20)
    lidar, camera = robot.getDevice("lidar"), robot.getDevice("camera")
    gyro = robot.getDevice("imu_gyro")
    gyro.enable(20)
    gyro_yaw, gyro_time = 0., robot.getTime()
    lidar.enable(100)
    camera.enable(200)
    connection = socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=5)
    connection.settimeout(.5)
    stream = connection.makefile("rwb")
    stream.write((json.dumps({"token": sys.argv[2]})+"\n").encode()); stream.flush()
    count, collisions = 0, 0
    last_command = time.monotonic()
    exit_code = 0
    try:
        while robot.step(20) != -1:
            count += 1
            # Integrate a simulated physical angular-rate sensor at the physics
            # rate, before downsampling packets. Never derive odometry heading
            # from Supervisor.getOrientation()/ground truth below.
            sensor_time = robot.getTime()
            yaw_rate = gyro.getValues()[2]
            if not math.isfinite(yaw_rate):
                raise RuntimeError("Invalid gyro angular-rate sample")
            gyro_yaw += yaw_rate*(sensor_time-gyro_time)
            gyro_time = sensor_time
            if time.monotonic()-last_command > .6:
                for motor in motors: motor.setVelocity(0.)
            if count % 5:
                continue
            sim_time = robot.getTime()
            ranges = lidar.getRangeImage()
            hits = [math.isfinite(r) and .05 <= r < 9 for r in ranges]
            ranges = [min(9., max(.05, r)) if math.isfinite(r) else 9. for r in ranges]
            angles = lidar_angles(len(ranges), lidar.getFov())
            wheels = [encoder.getValue() for encoder in encoders]
            position, orientation = robot.getSelf().getPosition(), robot.getSelf().getOrientation()
            pose = [position[0], position[1], math.atan2(orientation[3], orientation[0])]
            # Root-only contacts exclude wheels; no guessed body-height cutoff.
            wheel_contacts = [(wheel.getPosition()[2], wheel.getContactPoints(False)) for wheel in wheel_nodes]
            blocked = (bool(robot.getSelf().getContactPoints(False)) or
                       any(p.point[2] >= z-info['radius']/2 for z, contacts in wheel_contacts for p in contacts))
            if not ready or preview:
                supported = sum(any(p.point[2] < z-info['radius']/2 for p in contacts)
                                for z, contacts in wheel_contacts)
                sensors_ready = (len(ranges) > 0 and all(math.isfinite(v) for v in wheels)
                                 and camera.getImage() is not None
                                 and all(not math.isnan(v) and v > 0 for v in lidar.getRangeImage()))
                result = placement.update(sim_time-placement_started, position, orientation, robot.getSelf().getVelocity(),
                                          blocked, supported, sensors_ready)
                if search and search.status != 'idle':
                    point = search.update(sim_time,result)
                    if point is not None:
                        move_probe(point,sim_time)
                        result = dict(status='checking', reasons=['Settling the next candidate'],can_use_observed=False)
                    result['search'] = search.report()
                    # A suggestion never authorizes applying a different saved
                    # pose. The user adopts it and validates a fresh preview.
                    result['status'] = 'checking' if search.status=='searching' else 'invalid'
                    if search.status=='searching': result['can_use_observed']=False
                stream.write((json.dumps({'startup': result})+'\n').encode()); stream.flush()
                response = stream.readline(10000)
                if not response:
                    break
                command = json.loads(response)
                if command.get('stop'): break
                for motor in motors: motor.setVelocity(0.)
                gyro_yaw = 0.
                if preview:
                    if command.get('placement_action')=='search':
                        point=search.start(sim_time)
                        if point is not None: move_probe(point,sim_time)
                    elif command.get('placement_action')=='cancel':
                        search.cancel()
                    continue
                if result['status'] != 'valid' and sim_time >= STARTUP_TIMEOUT_SECONDS:
                    raise RuntimeError('Unsafe startup: '+ '; '.join(result['reasons'])+
                                       f". World: {config.get('webots_world') or 'Generated room'}; "
                                       f"observed XYZ: {result['observed_position']}. "
                                       'Open World setup and check robot placement.')
                ready = result['status'] == 'valid'
                # No sensor publication or queued drive command during settling.
                continue
            collisions += int(blocked)
            scan = {"ranges": ranges, "angles": angles, "hits": hits, "range_max": 9.,
                "offset": info["mounts"]["lidar_link"], "frame": config["drive"]["lidar_frame"]}
            packet = {"time": sim_time, "pose": pose, "wheels": wheels, "gyro_yaw": gyro_yaw,
                "scan": scan, "collisions": collisions, "blocked": blocked}
            if count % 10 == 0:
                packet["camera_bgra"] = base64.b64encode(camera.getImage()).decode()
            stream.write((json.dumps(packet, allow_nan=False)+"\n").encode()); stream.flush()
            response = stream.readline(10000)
            if not response:
                break
            command = json.loads(response)
            if command.get("stop"):
                break
            linear, angular = command["linear"], command["angular"]
            left = (linear-angular*info["track"]/2)/info["radius"]
            right = (linear+angular*info["track"]/2)/info["radius"]
            for motor, velocity in zip(motors, [left,left,right,right]):
                limit = config['physics']['motor_max_velocity']
                motor.setVelocity(max(-limit, min(limit, velocity)))
            last_command = time.monotonic()
    except Exception as exc:
        exit_code = 1
        error = f'{type(exc).__name__}: {exc}'
        print(f'PyRobot controller stopped: {error}', file=sys.stderr, flush=True)
        try:
            stream.write((json.dumps({'error': error})+'\n').encode())
            stream.flush()
        except (OSError, ValueError):
            pass
    finally:
        for motor in motors: motor.setVelocity(0.)
        robot.simulationQuit(exit_code)
        robot.step(20)
        connection.close()


if __name__ == "__main__":
    main()
