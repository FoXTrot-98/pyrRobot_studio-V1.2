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
    robot = Supervisor()
    info = json.loads((Path(__file__).parent/"robot.json").read_text())
    config, joints = info["config"], info["joints"]
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
            contacts=robot.getSelf().getContactPoints(True)
            blocked = any(point.point[2] > position[2]+.04 for point in contacts)
            if config.get('webots_world') and (blocked or orientation[8]<.85 or abs(position[2]-config.get('spawn_height',.002))>.3) and count<=25:
                stream.write((json.dumps({'error':'Unsafe spawn: body contact, tipping or unsupported floor height. Stop and adjust World setup spawn X/Y/height.'})+'\n').encode());stream.flush()
                break
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
                motor.setVelocity(max(-20., min(20., velocity)))
            last_command = time.monotonic()
    finally:
        for motor in motors: motor.setVelocity(0.)
        robot.simulationQuit(0)
        robot.step(20)
        connection.close()


if __name__ == "__main__":
    main()
