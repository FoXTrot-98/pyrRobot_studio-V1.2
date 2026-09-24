"""Encoder odometry, local scan-to-submap SLAM, occupancy A* and path following.

Algorithms consume sensor messages only. No simulator obstacle list or true pose
is imported here. SLAM is local: no global loop-closure or kidnapped-robot recovery.
"""
import heapq
import math
import cv2
import numpy as np

from .world import advance, sensor_pose, wrap


class WheelOdometry:
    def __init__(self):
        self.pose = np.zeros(3)
        self.previous = np.zeros(4)

    def update(self, ticks, radius, track, ticks_per_turn=4096):
        angles = np.asarray(ticks) * (2*math.pi/ticks_per_turn)
        delta = (angles - self.previous) * radius
        self.previous = angles
        left, right = np.mean(delta[:2]), np.mean(delta[2:])
        self.pose = advance(self.pose, (left+right)/2, (right-left)/track)
        return self.pose.copy()


class LidarSlam:
    def __init__(self, resolution=.12, origin=(-2.4, -2.4), size=(108, 91)):
        self.resolution, self.origin = resolution, np.array(origin)
        self.grid = np.zeros((size[1], size[0]), dtype=np.float32)
        self.pose, self.last_odom = np.zeros(3), np.zeros(3)
        self.frames = 0
        self.submaps = []
        self.keyframe_poses = []

    def cells(self, points):
        return np.floor((np.asarray(points)-self.origin)/self.resolution).astype(int)

    def endpoints(self, pose, scan):
        mount = sensor_pose(pose, scan["offset"])
        angles = np.asarray(scan["angles"]) + mount[2]
        points = mount[:2] + np.asarray(scan["ranges"])[:, None] * np.stack([np.cos(angles), np.sin(angles)], axis=1)
        return mount, points

    def update(self, odometry, scan):
        odometry = np.asarray(odometry)
        delta = odometry[:2] - self.last_odom[:2]
        correction = self.pose[2] - self.last_odom[2]
        c, s = math.cos(correction), math.sin(correction)
        predicted = self.pose + [c*delta[0]-s*delta[1], s*delta[0]+c*delta[1], wrap(odometry[2]-self.last_odom[2])]
        predicted[2] = wrap(predicted[2])
        best = predicted.copy()
        if self.submaps and any(len(entry[0]) for entry in self.submaps):
            # Reuse spatial anchors when revisiting a place. Replacing all
            # references every two seconds integrated scan noise into map drift.
            distances = [np.linalg.norm(p[:2]-predicted[:2]) for p in self.keyframe_poses]
            nearby = sorted(range(len(distances)), key=lambda i: (distances[i], i))[:8]
            reference = np.concatenate([self.submaps[i][0] for i in nearby])
            normals = np.concatenate([self.submaps[i][1] for i in nearby])
            valid = np.asarray(scan["hits"], dtype=bool)
            # Local point-to-plane ICP against recent scan keyframes. Odometry
            # seeds the estimate; least-squares surface residuals correct drift.
            for _ in range(7):
                _, points = self.endpoints(best, scan)
                points = points[valid][::3]
                squared = np.sum((points[:, None, :] - reference[None, :, :])**2, axis=2)
                nearest = np.argmin(squared, axis=1)
                keep = squared[np.arange(len(points)), nearest] < .4**2
                if np.count_nonzero(keep) < 20:
                    break
                points, targets, n = points[keep], reference[nearest[keep]], normals[nearest[keep]]
                relative = points - best[:2]
                residual = np.sum(n*(points-targets), axis=1)
                keep = np.abs(residual) < .15
                jacobian = np.column_stack([n[:,0], n[:,1], -n[:,0]*relative[:,1]+n[:,1]*relative[:,0]])[keep]
                if len(jacobian) < 20:
                    break
                # Small odometry regularizer resolves underconstrained corridors.
                lhs = jacobian.T @ jacobian + np.diag([.2, .2, .3])
                update = np.linalg.solve(lhs, -jacobian.T @ residual[keep])
                update = np.clip(update, [-.06,-.06,-.03], [.06,.06,.03])
                best += update
                if np.linalg.norm(update) < 1e-4:
                    break
        self.pose, self.last_odom = best, odometry.copy()
        self.pose[2] = wrap(self.pose[2])
        mount, points = self.endpoints(self.pose, scan)
        # Add an anchor only after leaving previously anchored positions/headings.
        anchored = any(np.linalg.norm(p[:2]-self.pose[:2]) < .35 and
                       abs(wrap(p[2]-self.pose[2])) < .35 for p in self.keyframe_poses)
        if not anchored:
            tangent = np.roll(points, -1, axis=0) - np.roll(points, 1, axis=0)
            lengths = np.linalg.norm(tangent, axis=1)
            valid = np.asarray(scan["hits"], dtype=bool) & (lengths > .02) & (lengths < .6)
            normals = np.column_stack([-tangent[:, 1], tangent[:, 0]]) / np.maximum(lengths[:, None], 1e-9)
            if np.count_nonzero(valid) >= 20:
                self.submaps.append((points[valid][::2].copy(), normals[valid][::2].copy()))
                self.keyframe_poses.append(self.pose.copy())
                self.submaps = self.submaps[-64:]
                self.keyframe_poses = self.keyframe_poses[-64:]
        height, width = self.grid.shape
        free_cells = []
        # Batch ray samples instead of allocating hundreds of linspace arrays.
        # Chunks bound temporary memory while retaining one vote/cell/scan.
        for offset in range(0, len(points), 64):
            delta = points[offset:offset+64] - mount[:2]
            steps = np.maximum(2, (np.linalg.norm(delta, axis=1)/self.resolution*1.3).astype(int))
            samples = np.arange(int(steps.max())-1)[None, :]
            fractions = samples/(steps[:, None]-1)
            samples_xy = mount[:2] + fractions[:, :, None]*delta[:, None, :]
            cells = self.cells(samples_xy[samples < steps[:, None]-1])
            inside = (cells[:, 0]>=0)&(cells[:, 0]<width)&(cells[:, 1]>=0)&(cells[:, 1]<height)
            cells = cells[inside]
            free_cells.append(cells[:, 1]*width + cells[:, 0])
        # Each cell gets one free-space vote per scan, not one per crossing ray.
        hits = self.cells(points[np.asarray(scan["hits"], dtype=bool)])
        inside = (hits[:, 0]>=0)&(hits[:, 0]<width)&(hits[:, 1]>=0)&(hits[:, 1]<height)
        hits = hits[inside]
        occupied = np.unique(hits[:, 1]*width+hits[:, 0])
        if free_cells:
            flat = np.setdiff1d(np.unique(np.concatenate(free_cells)), occupied)
            self.grid.flat[flat] -= .35
        if len(hits):
            self.grid.flat[occupied] += 1.2
        np.clip(self.grid, -4, 4, out=self.grid)
        self.frames += 1
        return self.pose.copy(), points

    def state(self, scan, sim_time):
        occupancy = np.full(self.grid.shape, -1, dtype=np.int8)
        occupancy[self.grid < -.1] = 0
        occupancy[self.grid > .7] = 100
        return {"pose": self.pose.tolist(), "grid": occupancy.tolist(), "resolution": self.resolution,
                "origin": self.origin.tolist(), "scan": scan, "time": sim_time,
                "mapped_cells": int(np.count_nonzero(occupancy >= 0)), "algorithm": "encoder + local point-to-plane scan-to-submap ICP"}


def plan_path(grid, origin, resolution, start, goal, radius=.65):
    """8-connected A* with obstacle inflation and no diagonal corner cutting.

    Unknown space is traversable at higher cost; the local lidar stop guards the
    robot as new obstacles become visible. Occupancy comes only from measured scans.
    """
    grid, origin = np.asarray(grid), np.asarray(origin)
    height, width = grid.shape
    cells = int(math.ceil(radius/resolution))
    offsets = np.arange(-cells, cells+1)*resolution
    # Respect the configured metric clearance; rounding the entire radius up
    # could mark the robot's current cell blocked on the next noisy scan.
    kernel = (offsets[:, None]**2+offsets[None, :]**2 <= radius**2).astype(np.uint8)
    blocked = cv2.dilate((grid >= 50).astype(np.uint8), kernel).astype(bool)
    def cell(point):
        return tuple(np.floor((np.asarray(point[:2])-origin)/resolution).astype(int))
    start, goal = cell(start), cell(goal)
    def valid(p):
        return 0 <= p[0] < width and 0 <= p[1] < height and not blocked[p[1], p[0]]
    if not valid(start) or not valid(goal):
        return []
    frontier, costs, parent = [(0.0, start)], {start: 0.0}, {}
    while frontier:
        _, current = heapq.heappop(frontier)
        if current == goal:
            path = [current]
            while current in parent:
                current = parent[current]
                path.append(current)
            return [(origin+(np.array(c)+.5)*resolution).tolist() for c in reversed(path)]
        for dx, dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
            nxt = (current[0]+dx, current[1]+dy)
            if not valid(nxt):
                continue
            if dx and dy and (not valid((current[0]+dx, current[1])) or not valid((current[0], current[1]+dy))):
                continue
            cost = costs[current] + math.hypot(dx,dy) * (2.5 if grid[nxt[1],nxt[0]] < 0 else 1.0)
            if cost < costs.get(nxt, float("inf")):
                costs[nxt], parent[nxt] = cost, current
                heapq.heappush(frontier, (cost+math.dist(nxt,goal), nxt))
    return []


def follow_path(pose, path, goal, scan, max_speed=.65, stop_distance=.55):
    if math.dist(pose[:2], goal) < .25:
        return 0.0, 0.0, "goal_reached"
    if not path:
        return 0.0, 0.0, "no_path"
    points = np.asarray(path)
    nearest = int(np.argmin(np.linalg.norm(points-np.asarray(pose[:2]), axis=1)))
    target = points[min(nearest+4, len(points)-1)]
    error = wrap(math.atan2(target[1]-pose[1], target[0]-pose[0])-pose[2])
    angular = float(np.clip(2.4*error, -1.3, 1.3))
    linear = max_speed * max(0, 1-abs(error)/.65)
    angles = np.asarray(scan["angles"]) + scan["offset"][2]
    angles = (angles+np.pi) % (2*np.pi)-np.pi
    front = np.abs(angles) < .45
    if linear > 0 and np.any(front) and min(np.asarray(scan["ranges"])[front]) < stop_distance:
        return 0.0, angular, "obstacle_stop"
    return linear, angular, "navigating"
