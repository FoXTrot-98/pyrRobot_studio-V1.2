"""Generic device bridge, copied beside a native Webots example world."""
import base64
import json
import math
from pathlib import Path
import socket
import sys


def main():
    from controller import Supervisor, Motor, Camera, Motion
    robot=Supervisor(); step=int(robot.getBasicTimeStep())
    directory=Path(__file__).parent
    config=json.loads((directory/'profile.json').read_text())
    motors={}; sensors={}; cameras=[]
    for i in range(robot.getNumberOfDevices()):
        device=robot.getDeviceByIndex(i)
        if isinstance(device,Motor):
            motors[device.getName()]=device
            sensor=device.getPositionSensor()
            if sensor: sensor.enable(step); sensors[device.getName()]=sensor
        elif isinstance(device,Camera): cameras.append(device)
    camera=cameras[0] if cameras else None
    if camera: camera.enable(step*max(1,round(200/step)))
    wheels=[motors[f'wheel{i}'] for i in range(1,5)] if config['profile']=='youbot' else []
    for motor in wheels: motor.setPosition(float('inf')); motor.setVelocity(0.)
    if robot.step(step)==-1: return
    motion=None
    def hold():
        nonlocal motion
        if motion: motion.stop(); motion=None
        for name,motor in motors.items():
            if motor in wheels: motor.setVelocity(0.); continue
            if name in sensors:
                position=sensors[name].getValue()
                if math.isfinite(position): motor.setPosition(position)
            motor.setVelocity(min(motor.getMaxVelocity(),.5 if motor.getType()==Motor.ROTATIONAL else .03) if name in sensors else 0.)
    def targets(values):
        # Validate the complete request before moving any joint.
        checked=[]
        for name,value in values.items():
            if name not in motors or motors[name] in wheels: raise ValueError(f'Unknown position-controlled motor: {name}')
            motor=motors[name]; minimum,maximum=motor.getMinPosition(),motor.getMaxPosition()
            if not math.isfinite(value) or (minimum!=maximum and not minimum<=value<=maximum):
                raise ValueError(f'{name}: target outside [{minimum}, {maximum}]')
            checked.append((motor,value))
        for motor,value in checked:
            motor.setVelocity(min(motor.getMaxVelocity(),.5 if motor.getType()==Motor.ROTATIONAL else .03))
            motor.setPosition(value)
    hold()
    connection=socket.create_connection(('127.0.0.1',int(sys.argv[1])),timeout=10)
    connection.settimeout(2.)
    stream=connection.makefile('rwb')
    stream.write((json.dumps({'token':sys.argv[2]})+'\n').encode()); stream.flush()
    last_id=None; status='holding'; error=''; count=0
    try:
        while robot.step(step)!=-1:
            count+=1
            if count % max(1,round(100/step)): continue
            joints=[]
            for name,motor in motors.items():
                if name not in sensors: continue
                value=sensors[name].getValue()
                if math.isfinite(value):
                    joints.append({'name':name,'position':value,'unit':'rad' if motor.getType()==Motor.ROTATIONAL else 'm'})
            packet={'time':robot.getTime(),'profile':config['profile'],'joints':joints,
                    'position':robot.getSelf().getPosition(),'status':status,'error':error}
            if camera and count % (2*max(1,round(100/step)))==0:
                packet['camera']={'width':camera.getWidth(),'height':camera.getHeight(),
                                  'name':camera.getName(),'bgra':base64.b64encode(camera.getImage()).decode()}
            stream.write((json.dumps(packet,allow_nan=False)+'\n').encode()); stream.flush()
            raw=stream.readline(65536)
            if not raw: break
            command=json.loads(raw)
            if command['id']!=last_id:
                last_id=command['id']; error=''
                try:
                    action=command['action']
                    if action=='hold': hold(); status='holding'
                    elif action=='targets':
                        hold(); targets(command['targets']); status='joint targets applied'
                    elif action in config.get('motions',{}):
                        hold(); motion=Motion(str(directory/config['motions'][action])); motion.play(); status=action
                    elif action in config['poses']:
                        if motion: motion.stop(); motion=None
                        targets(config['poses'][action]); status=action
                    else: raise ValueError(f'Unsupported action: {action}')
                except Exception as exc: hold(); status='command rejected'; error=str(exc)
            if motion and motion.isOver(): status='motion complete'
            if wheels:
                linear=max(-.2,min(.2,command.get('linear',0.)))
                angular=max(-.5,min(.5,command.get('angular',0.)))
                # Official youBot wheel order: left turn [-,+,-,+].
                for motor,sign in zip(wheels,[-1,1,-1,1]):
                    motor.setVelocity((linear+sign*.386*angular)/.05)
    finally:
        hold()
        connection.close()
        robot.simulationQuit(0); robot.step(step)


if __name__=='__main__': main()
