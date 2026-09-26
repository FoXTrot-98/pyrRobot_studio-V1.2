"""Rerun sink: truth is used only for visualization and error comparison."""
import base64
import math
import cv2
import numpy as np
import rerun as rr
import rerun.blueprint as rrb

from sdk.pyrobot_plugin import PluginManifest, PortSpec, PortDataType as T
from core.simulation.worker import WorkerNode
from core.simulation.world import sensor_pose
from core.urdf.model import origin_matrix
from core.simulation.mesh_robot import mesh_data


def cylinder_mesh(radius, length):
    angles = np.linspace(0, 2*np.pi, 24, endpoint=False)
    ring = np.column_stack([radius*np.cos(angles), radius*np.sin(angles)])
    vertices = np.concatenate([np.column_stack([ring, np.full(24, -length/2)]),
                               np.column_stack([ring, np.full(24, length/2)]), [[0,0,-length/2], [0,0,length/2]]])
    faces = []
    for i in range(24):
        j = (i+1)%24
        faces.extend([[i,j,j+24],[i,j+24,i+24],[48,j,i],[49,i+24,j+24]])
    return vertices, faces


class SimulationRerunView(WorkerNode):
    manifest = PluginManifest(id="pyrobot.sim.rerun_view", name="Robot simulation / Rerun", category="Visualization",
        description="URDF robot, simulated world, estimated map/pose, lidar, planned path, perspective camera and navigation status.",
        inputs=[PortSpec("truth", T.JSON), PortSpec("state", T.JSON, schema="pyrobot/MappingState@1"), PortSpec("path", T.JSON, schema="pyrobot/NavigationPath@1"), PortSpec("camera", T.IMAGE, schema="pyrobot/Image@1")])

    def on_start(self):
        if self.robot_model is None:
            raise ValueError("Load the robot URDF")
        if rr.get_application_id() is None:
            rr.init("pyrobot-simulation", spawn=False)
        self.truth, self.estimate, self.route = None, None, None
        self.trajectory = []
        self._world_logged = False
        self._frames = 0
        self._chains = {name: [(joint, origin_matrix(joint.origin)) for joint in self.robot_model.path_to_root(name)]
                        for name in self.robot_model.links}
        base = np.eye(4)
        for joint, matrix in self._chains[self.robot_config.drive.base_frame]:
            if joint.joint_type != "fixed":
                raise ValueError("Simulator base frame needs a fixed path to the URDF root")
            base = base @ matrix
        self._base_inverse = np.linalg.inv(base)
        self._lidar_height = self.robot_model.static_transform(self.robot_config.drive.base_frame,
            self.robot_config.drive.lidar_frame)["xyz"][2]
        rr.log("simulation", rr.Clear(recursive=True))
        rr.log("simulation", rr.ViewCoordinates.RIGHT_HAND_Z_UP, static=True)
        rr.send_blueprint(rrb.Blueprint(rrb.Horizontal(
            rrb.Spatial3DView(origin="/simulation", name="Robot / lidar / SLAM / path",
                eye_controls=rrb.EyeControls3D(position=[13,-10,13], look_target=[4,3,0], eye_up=[0,0,1])),
            rrb.Vertical(rrb.Spatial2DView(origin="/camera", name="Simulated camera"),
                         rrb.Spatial2DView(origin="/map", name="Measured occupancy map"),
                         rrb.TextDocumentView(origin="/navigation", name="Navigation status")),
            column_shares=[3, 1.2]), collapse_panels=True))
        self._log_robot_geometry()
        self.start_worker()

    def _log_robot_geometry(self):
        for name, link in self.robot_model.links.items():
            geometry = link.visual_geometry
            if not geometry:
                continue
            entity = f"simulation/robot/{name}/visual"
            visual = origin_matrix(link.visual_origin)
            rr.log(entity, rr.Transform3D(translation=visual[:3,3], mat3x3=visual[:3,:3]), static=True)
            color = [int(c*255) for c in link.color]
            if geometry["type"] == "box":
                rr.log(entity, rr.Boxes3D(sizes=[list(map(float, geometry["size"].split()))], colors=color), static=True)
            elif geometry['type'] == 'mesh':
                vertices, triangles, normals, colors = mesh_data(self.robot_model,link)
                rr.log(entity, rr.Mesh3D(vertex_positions=vertices, triangle_indices=triangles,
                    vertex_normals=normals, vertex_colors=np.rint(np.asarray(colors)*255).astype(np.uint8)), static=True)
            elif geometry["type"] == "cylinder":
                vertices, triangles = cylinder_mesh(float(geometry["radius"]), float(geometry["length"]))
                rr.log(entity, rr.Mesh3D(vertex_positions=vertices, triangle_indices=triangles, albedo_factor=color), static=True)
                if "wheel" in name:
                    radius = float(geometry["radius"])
                    rr.log(entity+"/spoke", rr.LineStrips3D([[[0,0,.052],[radius,0,.052]]], colors=[240,240,245], radii=.008), static=True)

    def process(self, port, payload):
        rr.set_time("simulation_time", duration=payload["time"])
        if port == "truth":
            self.truth = payload
            if not self._world_logged:
                boxes = payload["obstacles"]
                centers = [[(b[0]+b[2])/2,(b[1]+b[3])/2,b[4]/2] for b in boxes]
                sizes = [[b[2]-b[0],b[3]-b[1],b[4]] for b in boxes]
                rr.log("simulation/environment", rr.Boxes3D(centers=centers,sizes=sizes,colors=[100,120,140,150],
                    fill_mode=rr.components.FillMode.TransparentFillMajorWireframe), static=True)
                a,b,c,d = payload["bounds"]
                rr.log("simulation/floor", rr.Boxes3D(centers=[[(a+c)/2,(b+d)/2,-.04]],sizes=[[c-a,d-b,.08]],colors=[65,75,85,180],
                    fill_mode=rr.components.FillMode.Solid), static=True)
                self._world_logged = True
            x,y,yaw = payload["pose"]
            rr.log("simulation/robot", rr.Transform3D(translation=[x,y,0], rotation=rr.RotationAxisAngle([0,0,1], radians=yaw)))
            angles = dict(zip(payload["joint_names"], payload["wheels"]))
            for name in self.robot_model.links:
                matrix = self._base_inverse.copy()
                for joint, origin in self._chains[name]:
                    matrix = matrix @ origin
                    if joint.name in angles:
                        angle = angles[joint.name]
                        c,s = math.cos(angle),math.sin(angle)
                        axis = np.asarray(joint.axis, dtype=float)
                        axis /= np.linalg.norm(axis)
                        x,y,z = axis
                        skew = np.array([[0,-z,y],[z,0,-x],[-y,x,0]])
                        rotation = np.eye(4)
                        rotation[:3,:3] = c*np.eye(3)+(1-c)*np.outer(axis,axis)+s*skew
                        matrix = matrix @ rotation
                rr.log(f"simulation/robot/{name}", rr.Transform3D(translation=matrix[:3,3],mat3x3=matrix[:3,:3]))
        elif port == "camera":
            image = cv2.imdecode(np.frombuffer(base64.b64decode(payload["jpeg_base64"]), dtype=np.uint8),cv2.IMREAD_COLOR)
            rr.log("camera/image", rr.Image(cv2.cvtColor(image,cv2.COLOR_BGR2RGB)))
        elif port == "state":
            self.estimate = payload
            pose = payload["pose"]
            rr.log("simulation/estimated_pose", rr.Boxes3D(centers=[[pose[0],pose[1],.3]],sizes=[[.82,.62,.28]],
                rotation_axis_angles=[rr.RotationAxisAngle([0,0,1], radians=pose[2])],colors=[255,209,75],fill_mode=rr.components.FillMode.MajorWireframe))
            self.trajectory.append([pose[0],pose[1],.06]);self.trajectory=self.trajectory[-2000:]
            rr.log("simulation/estimated_trail", rr.LineStrips3D([self.trajectory],colors=[255,203,74],radii=.025))
            scan = payload["scan"]
            mount = sensor_pose(pose, scan["offset"])
            angles = np.asarray(scan["angles"])+mount[2]
            points = mount[:2]+np.asarray(scan["ranges"])[:,None]*np.column_stack([np.cos(angles),np.sin(angles)])
            lidar_height = self._lidar_height
            rr.log("simulation/lidar_hits",rr.Points3D(np.column_stack([points,np.full(len(points),lidar_height)]),colors=[60,230,190],radii=.025))
            rays = [[[mount[0],mount[1],lidar_height],[p[0],p[1],lidar_height]] for p in points[::8]]
            rr.log("simulation/lidar_rays",rr.LineStrips3D(rays,colors=[45,170,165,65],radii=.004))
            self._frames += 1
            if self._frames % 3 == 0:
                self._map(payload)
        elif port == "path":
            self.route = payload
            points = [[p[0],p[1],.09] for p in payload["points"]]
            rr.log("simulation/planned_path",rr.LineStrips3D([points] if points else [],colors=[89,152,255],radii=.045))
            rr.log("simulation/goal",rr.Points3D([[*payload["goal"],.15]],colors=[245,87,104],radii=.15,labels=["Goal"]))
        if self.route and port == "path":
            error = math.dist(self.truth["pose"][:2],self.estimate["pose"][:2]) if self.truth and self.estimate else 0
            distance = self.route.get("distance_to_goal")
            distance_text = f"{distance:.2f} m" if distance is not None else "Awaiting sensors"
            simulator = "Webots physics simulation" if self.truth and self.truth.get("source") == "webots" else "Built-in planar simulation"
            rr.log("navigation/status",rr.TextDocument(
                f"# {self.route['status'].replace('_',' ').title()}\n\n"
                f"Goal: {self.route['goal']} m\n\nDistance: {distance_text}\n\n"
                f"Pose error vs simulator: {error:.3f} m\n\n"
                f"Collision contacts: {self.truth['collisions'] if self.truth else 0}\n\n"
                "Blue: A* path · Yellow: estimated pose/map trail · Green: lidar\n\n"
                f"{simulator}. Local lidar SLAM; no loop closure. Camera is visualization only.", media_type="text/markdown"))

    def _map(self, payload):
        grid = np.asarray(payload["grid"])
        y,x = np.nonzero(grid >= 50)
        origin,res = np.asarray(payload["origin"]),payload["resolution"]
        occupied = origin + (np.column_stack([x,y])+.5)*res
        rr.log("simulation/measured_map",rr.Boxes3D(centers=np.column_stack([occupied,np.full(len(occupied),.08)]),
            sizes=[[res,res,.025]],colors=[250,194,63],fill_mode=rr.components.FillMode.Solid))
        image = np.full((*grid.shape,3),110,dtype=np.uint8)
        image[grid==0]=[228,235,239];image[grid>=50]=[30,45,65]
        if self.route and self.route["points"]:
            cells = ((np.asarray(self.route["points"])-origin)/res).astype(np.int32)
            cv2.polylines(image,[cells],False,(65,130,245),1)
        cell = ((np.asarray(payload["pose"][:2])-origin)/res).astype(int)
        cv2.circle(image,tuple(cell),2,(240,105,65),-1)
        rr.log("map/image",rr.Image(np.flipud(image).copy()))
