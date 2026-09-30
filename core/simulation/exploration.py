"""Reachable frontier selection on measured free space only."""
from collections import deque
import math
import cv2
import numpy as np


def frontier_goal(grid, origin, resolution, pose, radius, visited=()):
    grid = np.asarray(grid)
    free = (grid >= 0) & (grid < 50)
    unknown = (grid < 0).astype(np.uint8)
    cross = np.array([[0,1,0],[1,1,1],[0,1,0]], dtype=np.uint8)
    frontier = free & (cv2.dilate(unknown, cross) != 0)
    cells = math.ceil(radius / resolution)
    offsets = np.arange(-cells, cells + 1) * resolution
    kernel = (offsets[:,None]**2 + offsets[None,:]**2 <= radius**2).astype(np.uint8)
    safe = free & ~cv2.dilate((grid >= 50).astype(np.uint8), kernel).astype(bool)
    x, y = np.floor((np.asarray(pose[:2])-origin)/resolution).astype(int)
    h, w = grid.shape
    if not (0 <= x < w and 0 <= y < h):
        return None
    seeds = [(x,y)] if safe[y,x] else []
    if not seeds:
        from core.simulation.navigation import plan_path
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            nx,ny = x+dx,y+dy
            point = [origin[0]+(nx+.5)*resolution, origin[1]+(ny+.5)*resolution]
            if 0 <= nx < w and 0 <= ny < h and safe[ny,nx] and plan_path(
                    grid, origin, resolution, pose, point, radius=radius, known_only=True):
                seeds.append((nx,ny))
    queue, seen = deque(seeds), set(seeds)
    while queue:
        x,y = queue.popleft()
        point = [origin[0]+(x+.5)*resolution, origin[1]+(y+.5)*resolution]
        if frontier[y,x] and math.dist(point,pose[:2]) >= .5 and all(math.dist(point,v) >= .75 for v in visited):
            return point
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            nx,ny=x+dx,y+dy
            if 0 <= nx < w and 0 <= ny < h and safe[ny,nx] and (nx,ny) not in seen:
                seen.add((nx,ny))
                queue.append((nx,ny))
    return None


def exploration_path(payload, pose, goal, radius, algorithm="astar"):
    from core.simulation.navigation import plan_path
    return plan_path(payload["grid"],payload["origin"],payload["resolution"],pose,goal,
                     radius=radius,algorithm=algorithm,known_only=True)
