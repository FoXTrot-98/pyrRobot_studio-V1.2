# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Bounded preview-only placement probes; no world-specific coordinates."""
import math

PROBE_SECONDS = 3.0
MAX_CANDIDATES = 25


def candidates(config):
    x,y,yaw = config['spawn_pose']
    radius = config['drive']['collision_radius']
    spacing = max(.5,2*radius)
    mapping = config['mapping']
    a,b = mapping['origin']
    c = a+mapping['width']*mapping['resolution']
    d = b+mapping['height']*mapping['resolution']
    offsets = sorted(((i,j) for i in range(-2,3) for j in range(-2,3)),
                     key=lambda p:(p[0]**2+p[1]**2,p))
    return [[x+i*spacing,y+j*spacing,config['spawn_height'],yaw] for i,j in offsets
            if a+radius <= x+i*spacing < c-radius and b+radius <= y+j*spacing < d-radius][:MAX_CANDIDATES]


class PlacementSearch:
    def __init__(self, config):
        self.config = config
        self.points = []
        self.index = -1
        self.started = 0.
        self.status = 'idle'

    def start(self, now):
        self.points = candidates(self.config)
        self.index = -1
        self.status = 'searching'
        return self.next(now)

    def next(self, now):
        self.index += 1
        if self.index >= len(self.points):
            self.status = 'exhausted'
            return None
        self.started = now
        return self.points[self.index]

    def update(self, now, result):
        if self.status != 'searching':
            return None
        position = result.get('observed_position', [])
        if result.get('can_use_observed') and len(position)==3 and all(math.isfinite(v) for v in position):
            mapping=self.config['mapping']; radius=self.config['drive']['collision_radius']
            x,y=position[:2]; a,b=mapping['origin']
            if (a+radius <= x < a+mapping['width']*mapping['resolution']-radius and
                    b+radius <= y < b+mapping['height']*mapping['resolution']-radius):
                self.status = 'found'
                return None
        if now-self.started >= PROBE_SECONDS:
            return self.next(now)
        return None

    def cancel(self):
        self.status = 'cancelled'

    def report(self):
        return dict(status=self.status, attempt=min(self.index+1,len(self.points)), total=len(self.points))
