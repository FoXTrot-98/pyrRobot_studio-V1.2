# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""World-selection transactions for an empty project or one supported robot."""
import math
from pydantic import BaseModel, ConfigDict, Field
from core.runtime.robot_setup import revision
from core.runtime.project import ProjectDocument
from core.simulation.config import RobotConfiguration
from core.simulation.external_world import inspect, available

class WorldRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    path: str = Field(min_length=1,max_length=4096)
    revision: str
    spawn_pose: list[float] = Field(default=[0.,0.,0.],min_length=3,max_length=3)
    spawn_height: float = Field(default=.002,ge=-100,le=100)
    bounds: list[float] = Field(default=[-15.,-15.,15.,15.],min_length=4,max_length=4)
    resolution: float = Field(default=.15,ge=.02,le=2)
    reset_mission: bool = False
    source_hash: str = ""
    placement_token: str = ""

def executable(runtime):
    return next((n.node_obj.get_param('executable','') for n in runtime.graph.nodes.values() if n.plugin_id=='pyrobot.sim.webots'),'')

def catalog(runtime):
    error=None
    try: worlds=available(executable(runtime))
    except ValueError as exc:worlds=[];error=str(exc)
    m=runtime.graph.robot_config.mapping
    return {'worlds':worlds,'error':error,'revision':revision(runtime),
            'configuration':runtime.graph.robot_config.model_dump(),
            'bounds':[*m.origin,m.origin[0]+m.width*m.resolution,m.origin[1]+m.height*m.resolution],
            'empty':not runtime.graph.nodes}

def draft(runtime,request):
    if runtime.graph.to_dict()['running']:raise ValueError('Stop Graph before changing the world')
    if revision(runtime)!=request.revision:raise ValueError('Project changed. Close and reopen World setup')
    info=inspect(request.path,executable(runtime))
    if request.source_hash and request.source_hash!=info['sha256']:raise ValueError('World changed since preview. Check world again')
    document=runtime.export().model_dump(mode='json')
    simulators=[n for n in document['nodes'] if n['plugin_id'] in ('pyrobot.sim.webots','pyrobot.sim.four_wheel')]
    if document['nodes'] and len(simulators)!=1:raise ValueError('Use Robot setup to create a supported four-wheel simulation first')
    a,b,c,d=request.bounds
    if not (a<c and b<d):raise ValueError('Mapping bounds must have minimum X/Y smaller than maximum X/Y')
    configuration=document['robot_config']
    configuration.update(webots_world=info['path'],webots_world_hash=info['sha256'],spawn_pose=request.spawn_pose,spawn_height=request.spawn_height)
    configuration['mapping'].update(origin=[a,b],width=math.ceil((c-a)/request.resolution),height=math.ceil((d-b)/request.resolution),resolution=request.resolution)
    config=RobotConfiguration.model_validate(configuration)
    document.update(robot_config=config.model_dump(),saved_maps={})
    for node in document['nodes']:
        if node in simulators:
            node['plugin_id']='pyrobot.sim.webots'
            node['plugin_version']=runtime.registry.get(node['plugin_id']).manifest.version
            node['params']={key:value for key,value in node['params'].items() if key in ('executable','minimize')}
        elif node['plugin_id']=='pyrobot.navigation.astar':
            node['params'].update(home_pose=[],waypoints=[],goal_x=request.spawn_pose[0],goal_y=request.spawn_pose[1],enabled=False,explore=False,return_home=False,cancel_mission=False)
        elif node['plugin_id']=='pyrobot.control.selector':node['params']['mode']='stopped'
    return ProjectDocument.model_validate(document),{key:value for key,value in info.items() if key!='source'}
