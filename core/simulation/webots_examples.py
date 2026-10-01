# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Profiles reuse Webots R2025a sample worlds and native PROTO assets."""
import json
from pathlib import Path
import re
import shutil
import sys
from .webots_project import find_webots, ROOT

PROFILES = {
    'panda': {'title':'Panda robot arm', 'world':'franka_emika/panda/worlds/panda.wbt', 'proto':'Panda',
              'actions':['hold','reach_near','reach_far','open_gripper','close_gripper'],
              'poses':{'reach_near':{'panda_joint2':.37,'panda_joint4':-2.7,'panda_joint6':2.9},
                       'reach_far':{'panda_joint2':.74,'panda_joint4':-1.96,'panda_joint6':2.53},
                       'open_gripper':{'panda_finger::right':.02},'close_gripper':{'panda_finger::right':.012}}},
    'nao': {'title':'NAO humanoid', 'world':'softbank/nao/worlds/nao_demo.wbt', 'proto':'Nao',
            'actions':['hold','wave','wipe_forehead'], 'poses':{},
            'motions':{'wave':'HandWave.motion','wipe_forehead':'WipeForehead.motion'}},
    'youbot': {'title':'KUKA youBot mobile manipulator', 'world':'kuka/youbot/worlds/youbot.wbt','proto':'Youbot',
               'actions':['hold','arm_home','arm_front','open_gripper','close_gripper'],
               'poses':{'arm_home':{'arm1':0.,'arm2':1.57,'arm3':-2.635,'arm4':1.78,'arm5':0.},
                        'arm_front':{'arm1':0.,'arm2':0.,'arm3':-.77,'arm4':-1.21,'arm5':0.},
                        'open_gripper':{'finger::left':.025},'close_gripper':{'finger::left':0.}}},
}


def example_project(profile):
    if profile not in PROFILES: raise ValueError('Unknown Webots profile')
    nodes=[{'node_id':'robot','plugin_id':'pyrobot.sim.webots_model','plugin_version':'0.1.0',
            'params':{'profile':profile,'action':'hold','executable':'','minimize':False}},
           {'node_id':'viewer','plugin_id':'pyrobot.sim.webots_model_view','plugin_version':'0.1.0','params':{}}]
    connections=[{'from_node':'robot','from_port':port,'to_node':'viewer','to_port':port} for port in ('state','camera')]
    positions={'robot':{'x':350,'y':160},'viewer':{'x':650,'y':160}}
    if profile=='youbot':
        nodes.append({'node_id':'keyboard','plugin_id':'pyrobot.control.keyboard','plugin_version':'0.1.0',
                      'params':{'linear_speed':.15,'angular_speed':.35}})
        connections.append({'from_node':'keyboard','from_port':'cmd_vel','to_node':'robot','to_port':'cmd_vel'})
        positions['keyboard']={'x':60,'y':160}
    return {'format':'pyrobot-project','schema_version':2,'name':PROFILES[profile]['title'],
            'robot_urdf':None,'nodes':nodes,'connections':connections,'positions':positions}


def webots_home(executable=''):
    found=find_webots(executable)
    if not found: raise ValueError('Webots not found. Install Webots R2025a or choose its executable.')
    for parent in Path(found).parents:
        if (parent/'projects/robots').is_dir() and (parent/'resources/version.txt').is_file(): return parent
    raise ValueError('Cannot locate the Webots projects directory beside the executable')


def example_world(profile, executable=''):
    home=webots_home(executable)
    path=home/'projects/robots'/PROFILES[profile]['world']
    if not path.is_file(): raise ValueError(f'This Webots installation does not include {path.name}')
    return path


def attach_controller(source, proto, controller, args):
    """Change only fields on one top-level robot, respecting strings/comments."""
    tokens=[m for m in re.finditer(r'#[^\n]*|"(?:\\.|[^"\\])*"|[{}\[\]]|[^\s{}\[\]"]+',source) if not m.group().startswith('#')]
    depth=0; blocks=[]
    for i,token in enumerate(tokens):
        value=token.group()
        if depth==0 and value==proto and i+1<len(tokens) and tokens[i+1].group()=='{':
            nesting=1; j=i+2
            while j<len(tokens) and nesting:
                nesting += (tokens[j].group()=='{')-(tokens[j].group()=='}'); j+=1
            if nesting: raise ValueError('Unclosed robot block in Webots world')
            blocks.append((i+1,j-1))
        depth += (value in ('{','['))-(value in ('}',']'))
    if len(blocks)!=1: raise ValueError(f'Expected one top-level {proto} in the example world, found {len(blocks)}')
    start,end=blocks[0]; edits=[]; depth=0; i=start+1
    fields={'controller','controllerArgs','supervisor','window'}
    while i<end:
        value=tokens[i].group()
        if depth==0 and value in fields:
            last=i+1
            if tokens[last].group()=='[':
                nesting=1; last+=1
                while nesting:
                    nesting+=(tokens[last].group()=='[')-(tokens[last].group()==']')
                    last+=1
                last-=1
            edits.append((tokens[i].start(),tokens[last].end(),'')); i=last+1; continue
        depth+=(value in ('{','['))-(value in ('}',']')); i+=1
    insertion=f'\n  controller {json.dumps(controller)}\n  controllerArgs {json.dumps(args)}\n  supervisor TRUE\n  window "<none>"\n'
    edits.append((tokens[start].end(),tokens[start].end(),insertion))
    for first,last,text in sorted(edits,reverse=True): source=source[:first]+text+source[last:]
    return source


def prepare_example(directory, profile, executable, port, token):
    source=example_world(profile,executable)
    worlds=Path(directory)/'worlds'; controller=Path(directory)/'controllers/studio_bridge'
    worlds.mkdir(parents=True,exist_ok=True); controller.mkdir(parents=True,exist_ok=True)
    world=attach_controller(source.read_text(encoding='utf-8'),PROFILES[profile]['proto'],'studio_bridge',[str(port),token])
    destination=worlds/source.name; destination.write_text(world,encoding='utf-8')
    shutil.copyfile(ROOT/'core/simulation/webots_model_controller.py',controller/'studio_bridge.py')
    (controller/'runtime.ini').write_text(f'[python]\nCOMMAND = {sys.executable}\n',encoding='utf-8')
    config={'profile':profile, **PROFILES[profile]}
    for filename in config.get('motions',{}).values():
        shutil.copyfile(source.parent.parent/'motions'/filename,controller/filename)
    (controller/'profile.json').write_text(json.dumps(config),encoding='utf-8')
    (Path(directory)/'SOURCE.txt').write_text(f'Original Webots world: {source}\nOnly the robot controller fields were changed.\nUpstream robot, mesh, world and motion licenses apply.\n',encoding='utf-8')
    return destination
