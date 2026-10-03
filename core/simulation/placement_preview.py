# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Own a motor-disabled Webots preview, independent of the running graph."""
import hashlib
import json
import threading
import time
import uuid

from core.urdf.model import parse_urdf
from core.urdf.assets import attach_assets
from plugins.user.webots_sim import WebotsSimulation
from core.simulation.placement_search import candidates


def fingerprint(request):
    data = request.model_dump(exclude={'reset_mission', 'placement_token'})
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


class PlacementPreview:
    def __init__(self, document, request, bus, executable):
        self.token = uuid.uuid4().hex
        self.fingerprint = fingerprint(request)
        self.last_poll = time.monotonic()
        self.stop = threading.Event()
        self.error = None
        self.searched = False
        self.node = WebotsSimulation(node_id='placement-preview', bus=bus,
                                     params={'executable': executable, 'minimize': False})
        self.node.robot_model = parse_urdf(document.robot_urdf)
        attach_assets(self.node.robot_model, document.robot_assets)
        self.node.robot_config = document.robot_config
        self.node.placement_preview = True
        self.thread = threading.Thread(target=self._run, name='world-placement', daemon=True)
        self.thread.start()

    def _run(self):
        try:
            self.node.on_start()
            while not self.stop.wait(.2):
                if self.node.error:
                    self.error = self.node.error
                    break
                if time.monotonic()-self.last_poll > 30:
                    self.error = 'Placement preview expired; check placement again'
                    break
        except Exception as exc:
            self.error = str(exc)
        finally:
            self.stop.set()
            self.node.on_stop()
            worker = getattr(self.node, '_thread', None)
            if worker:
                worker.join(timeout=6)

    def status(self):
        self.last_poll = time.monotonic()
        if self.error or self.stop.is_set():
            result = {'status': 'failed', 'reasons': [self.error or 'Preview closed']}
        else:
            result = getattr(self.node, 'placement_result', {'status': 'starting', 'reasons': []}).copy()
            if time.monotonic()-getattr(self.node, 'placement_updated', time.monotonic()) > 3:
                result = {'status': 'checking', 'reasons': ['Resume Webots to check the edited placement']}
            if self.searched and 'search' not in result:
                result.update(status='checking',can_use_observed=False,
                              search=dict(status='searching',attempt=0,total=len(candidates(self.node.robot_config.model_dump()))))
        return {**result, 'token': self.token}

    def require_valid(self, request):
        if self.searched:
            raise ValueError('Adopt the suggested Webots position and check it again before applying')
        if request.placement_token != self.token or fingerprint(request) != self.fingerprint:
            raise ValueError('World, robot or placement changed; check placement again')
        if self.status()['status'] != 'valid':
            raise ValueError('A valid physical placement check is required before applying this world')

    def action(self, action):
        status=self.status()
        if status['status'] in ('failed','starting'):
            raise ValueError('Wait for Webots to connect before searching')
        if action=='search':self.searched=True
        with self.node._command_lock:
            self.node.placement_action=action
        return self.status()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=15)
        if self.thread.is_alive():
            raise RuntimeError('Webots preview is still closing; wait before starting another simulation')
