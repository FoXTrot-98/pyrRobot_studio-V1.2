"""Plugin drafts, deterministic generation and bounded child-process tests."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import uuid
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from core.messages import SCHEMAS
from sdk.pyrobot_plugin import PortDataType

ROOT = Path(__file__).resolve().parents[2]
RESERVED_NAMES = {'con', 'prn', 'aux', 'nul'} | {f'{prefix}{i}' for prefix in ('com', 'lpt') for i in range(1, 10)}


class Port(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(pattern=r'^[a-z][a-z0-9_]{0,39}$')
    data_type: str = 'json'
    message_schema: str | None = Field(default=None, alias='schema')
    required: bool = True

    @model_validator(mode='after')
    def valid(self):
        PortDataType(self.data_type)
        if self.message_schema and self.message_schema not in SCHEMAS: raise ValueError('Unknown message schema')
        if self.message_schema and self.message_schema.endswith('/Image@1') and self.data_type != 'image':
            raise ValueError('Image messages require image ports')
        return self


class Parameter(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    name: str = Field(pattern=r'^[a-z][a-z0-9_]{0,39}$')
    kind: Literal['number', 'string', 'bool', 'json'] = 'number'
    default: object = 1
    min: float | None = None
    max: float | None = None


class Draft(BaseModel):
    model_config = ConfigDict(extra='forbid')
    slug: str = Field(pattern=r'^[a-z][a-z0-9_]{0,47}$')
    name: str = Field(min_length=1, max_length=100)
    version: str = Field(default='0.1.0', pattern=r'^\d+\.\d+\.\d+$')
    description: str = Field(default='', max_length=1000)
    template: Literal['sensor', 'processing'] = 'processing'
    inputs: list[Port] = Field(default_factory=list, max_length=16)
    outputs: list[Port] = Field(min_length=1, max_length=16)
    params: list[Parameter] = Field(default_factory=list, max_length=32)
    sample: dict = Field(default_factory=lambda: {'value': 1})

    @model_validator(mode='after')
    def valid(self):
        if self.slug in RESERVED_NAMES: raise ValueError('Choose a portable filename; this slug is reserved on Windows')
        for entries in (self.inputs, self.outputs, self.params):
            if len({p.name for p in entries}) != len(entries): raise ValueError('Names must be unique within each list')
        if self.template == 'sensor' and self.inputs: raise ValueError('Sensor template has no inputs')
        if self.template == 'processing' and not self.inputs: raise ValueError('Processing needs an input')
        return self


def generate(draft):
    from sdk.pyrobot_plugin import PluginManifest, ParamSpec
    from .graph import NodeGraph
    manifest = PluginManifest(id='user.' + draft.slug, name=draft.name, category='Sensors' if draft.template == 'sensor' else 'Processing',
        version=draft.version, description=draft.description, params=[ParamSpec(**p.model_dump()) for p in draft.params])
    NodeGraph._validate_params(manifest, {p.name: p.default for p in draft.params})
    ports = lambda values: '[' + ', '.join(f'PortSpec({p.name!r}, PortDataType.{p.data_type.upper()}, required={p.required!r}, schema={p.message_schema!r})' for p in values) + ']'
    source = ('"""Generated in Studio Plugin Builder. Trusted Python code."""\n'
        'import threading\nfrom sdk.pyrobot_plugin import Node, PluginManifest, PortSpec, PortDataType, ParamSpec\n\n'
        'class BuiltPlugin(Node):\n'
        f'    manifest = PluginManifest(id={manifest.id!r}, name={draft.name!r}, category={manifest.category!r}, version={draft.version!r}, description={draft.description!r},\n'
        f'        inputs={ports(draft.inputs)}, outputs={ports(draft.outputs)},\n'
        '        params=[' + ', '.join('ParamSpec(**' + repr(p.model_dump()) + ')' for p in draft.params) + '])\n\n')
    if draft.template == 'processing':
        source += '    def on_message(self, port, message):\n        result = dict(message.payload)  # Edit your processing here.\n'
        source += ''.join(f'        self.emit({p.name!r}, result)\n' for p in draft.outputs)
    else:
        source += ('    def on_start(self):\n        self._stop = threading.Event()\n'
            '        self._thread = threading.Thread(target=self._run, daemon=True)\n        self._thread.start()\n\n'
            '    def on_stop(self):\n        self._stop.set()\n\n'
            '    def _run(self):\n        try:\n            while not self._stop.is_set():\n'
            f'                result = {draft.sample!r}  # Replace with sensor capture.\n')
        source += ''.join(f'                self.emit({p.name!r}, result)\n' for p in draft.outputs)
        source += '                self._stop.wait(0.1)\n        except Exception as exc:\n            self.fail(exc)\n'
    ast.parse(source)
    return source


class TestRequest(BaseModel):
    source: str = Field(min_length=1, max_length=65536)
    sample: dict = Field(default_factory=dict)
    trusted: Literal[True]


class Builder:
    def __init__(self, directory=ROOT / 'artifacts/plugin-builder'):
        self.directory = Path(directory)
        self.jobs = {}
        self.lock = threading.RLock()

    def start(self, request):
        ast.parse(request.source)
        with self.lock:
            if any(j['status'] == 'running' for j in self.jobs.values()): raise ValueError('A plugin test is already running')
            if len(self.jobs) >= 64: self.jobs.pop(next(iter(self.jobs)))
            key = uuid.uuid4().hex
            path = self.directory / key
            path.mkdir(parents=True)
            (path / 'plugin.py').write_text(request.source, encoding='utf-8')
            (path / 'input.json').write_text(json.dumps(request.sample, allow_nan=False), encoding='utf-8')
            process = subprocess.Popen([sys.executable, '-m', 'core.runtime.plugin_test_worker', str(path)], cwd=ROOT,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
            self.jobs[key] = {'status': 'running', 'process': process, 'source': request.source, 'path': path}
            threading.Thread(target=self._wait, args=(key,), daemon=True).start()
            return {'id': key, 'status': 'running'}

    def _wait(self, key):
        job = self.jobs[key]
        try:
            job['process'].wait(timeout=8)
            path = job['path'] / 'result.json'
            if not path.exists() or path.stat().st_size > 131072: raise ValueError('Test worker exited without a valid report')
            result = json.loads(path.read_text(encoding='utf-8'))
            with self.lock:
                if job['status'] == 'running': job.update(status='passed' if result['ok'] else 'failed', result=result)
        except Exception as exc:
            job['process'].kill()
            job['process'].wait()
            with self.lock:
                if job['status'] == 'running': job.update(status='failed', result={'ok': False, 'error': 'Test timed out or failed: ' + str(exc)})

    def status(self, key):
        with self.lock:
            job = self.jobs[key]
            return {'id': key, 'status': job['status'], 'result': job.get('result')}

    def cancel(self, key):
        with self.lock:
            job = self.jobs[key]
            if job['status'] == 'running':
                job['status'] = 'cancelled'
                job['process'].kill()
            return self.status(key)

    def close(self):
        for key in list(self.jobs): self.cancel(key)

    def install(self, key, registry, destination=ROOT / 'plugins/user'):
        with self.lock:
            job = self.jobs[key]
            if job['status'] != 'passed': raise ValueError('Run a successful test before installing')
            manifest = job['result']['manifest']
            plugin_id = manifest['id']
            import re
            if not re.fullmatch(r'user\.[a-z][a-z0-9_]{0,47}', plugin_id): raise ValueError('Builder plugins must use user.<slug> IDs')
            if plugin_id[5:] in RESERVED_NAMES: raise ValueError('Plugin filename is reserved on Windows')
            if plugin_id in registry: raise ValueError('Plugin ID already installed; choose a new ID')
            target = Path(destination) / (plugin_id[5:] + '.py')
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('x', encoding='utf-8') as stream: stream.write(job['source'])
            return {'path': str(target), 'manifest': manifest, 'restart_required': True,
                    'sha256': hashlib.sha256(job['source'].encode()).hexdigest()}
