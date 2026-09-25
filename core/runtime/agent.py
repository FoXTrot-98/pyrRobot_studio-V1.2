"""Authenticated deployment agent. Run separately from the Studio backend."""
import argparse
from collections import deque
from contextlib import asynccontextmanager, contextmanager
import hashlib
import hmac
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import platform
import threading

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from .session import Runtime
from .project import ProjectDocument, prepare_project
from .__main__ import ValidationTransport
from core.bus.base import Bus
from core.timing.clock import PRTClock


class LogBuffer(logging.Handler):
    def __init__(self):
        super().__init__()
        self.rows = deque(maxlen=400)

    def emit(self, record):
        self.rows.append(self.format(record)[:2000])


def create_app(token, directory, runtime=None, origins=None):
    if len(token) < 32:
        raise ValueError('Agent token must contain at least 32 characters')
    runtime = runtime or Runtime()
    directory = Path(directory)
    log = LogBuffer()
    log.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    lock = threading.RLock()
    deployed = {'revision': None}

    @contextmanager
    def operation():
        if not lock.acquire(timeout=2):
            raise HTTPException(503, 'Agent is busy or blocked; command was not executed')
        try: yield
        finally: lock.release()

    def select_revision(revision):
        temporary = directory / 'current.tmp'
        with temporary.open('w', encoding='ascii') as stream:
            stream.write(revision)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / 'current')

    @asynccontextmanager
    async def lifespan(app):
        directory.mkdir(parents=True, exist_ok=True)
        disk_log = RotatingFileHandler(directory / 'agent.log', maxBytes=2_000_000, backupCount=4, encoding='utf-8')
        disk_log.setFormatter(log.formatter)
        logging.getLogger().addHandler(log)
        logging.getLogger().addHandler(disk_log)
        try:
            runtime.open()
            selected = directory / 'current'
            if selected.exists():
                try:
                    revision = selected.read_text(encoding='ascii').strip()
                    if len(revision) != 64 or any(c not in '0123456789abcdef' for c in revision):
                        raise ValueError('Invalid deployment revision pointer')
                    data = (directory / (revision + '.pyrobot.json')).read_bytes()
                    if hashlib.sha256(data).hexdigest() != revision:
                        raise ValueError('Stored project checksum mismatch')
                    doc = ProjectDocument.model_validate_json(data)
                    result = check(doc)
                    if not result['compatible']:
                        raise ValueError(str(result['diagnostics']))
                    runtime.load_project(doc)
                    deployed['revision'] = revision
                except Exception:
                    logging.getLogger('pyrobot.agent').exception('Deployment recovery failed; no project will start')
            yield
        finally:
            try: runtime.close()
            finally:
                logging.getLogger().removeHandler(log)
                logging.getLogger().removeHandler(disk_log)
                disk_log.close()

    app = FastAPI(title='PyRobot deployment agent', lifespan=lifespan)

    @app.middleware('http')
    async def authenticate(request, call_next):
        if request.method != 'OPTIONS' and not hmac.compare_digest(request.headers.get('authorization', '').encode(), ('Bearer ' + token).encode()):
            return JSONResponse({'detail': 'Invalid agent token'}, status_code=401)
        return await call_next(request)

    async def document(request):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 8 * 1024 * 1024:
                raise HTTPException(413, 'Project exceeds 8 MiB')
        try:
            return ProjectDocument.model_validate_json(data)
        except ValueError as exc:
            raise HTTPException(422, 'Invalid project document: ' + str(exc)[:1000]) from exc

    def check(doc):
        bus = Bus(ValidationTransport(), PRTClock('deployment-validation'))
        candidate = None
        try:
            candidate, _ = prepare_project(doc, bus, runtime.registry)
            diagnostics = candidate.preflight()
            return {'compatible': not diagnostics, 'diagnostics': diagnostics,
                    'note': 'Checks installed plugin versions, graph wiring and configuration. Hardware access and external assets must be verified on the target.'}
        except Exception as exc:
            return {'compatible': False, 'diagnostics': [{'message': str(exc)}]}
        finally:
            if candidate: candidate.close()
            bus.close()

    @app.get('/agent/status')
    def status():
        with operation():
            return {'protocol': 1, 'hostname': platform.node(), 'os': platform.system(),
                    'architecture': platform.machine(), 'python': platform.python_version(),
                    'project': runtime.name, 'revision': deployed['revision'], 'graph': runtime.graph.to_dict()}

    @app.get('/agent/logs')
    def logs():
        log.acquire()
        try: return {'lines': list(log.rows)}
        finally: log.release()

    @app.post('/agent/check')
    async def compatibility(request: Request):
        doc = await document(request)
        def work():
            with operation(): return check(doc)
        return await run_in_threadpool(work)

    @app.post('/agent/deploy')
    async def deploy(request: Request):
        doc = await document(request)
        return await run_in_threadpool(deploy_document, doc)

    def deploy_document(doc):
        with operation():
            if runtime.graph.to_dict()['running']:
                raise HTTPException(409, 'Stop the remote graph before transferring a project')
            result = check(doc)
            if not result['compatible']: raise HTTPException(422, result)
            data = doc.model_dump_json().encode()
            revision = hashlib.sha256(data).hexdigest()
            destination = directory / (revision + '.pyrobot.json')
            temporary = directory / 'upload.tmp'
            previous = runtime.export()
            try:
                temporary.write_bytes(data)
                os.replace(temporary, destination)
                runtime.load_project(doc)
                try:
                    select_revision(revision)
                except Exception:
                    runtime.load_project(previous)
                    raise
            except Exception as exc:
                raise HTTPException(400, str(exc)) from exc
            deployed['revision'] = revision
            logging.getLogger('pyrobot.agent').warning('Deployed project %s revision %s', doc.name, revision[:12])
            return status()

    @app.post('/agent/start')
    def start(body: dict):
        with operation():
            if not deployed['revision'] or body.get('revision') != deployed['revision']:
                raise HTTPException(409, 'Project revision changed; refresh remote status before starting')
            try: runtime.graph.start()
            except Exception as exc: raise HTTPException(400, str(exc)) from exc
            logging.getLogger('pyrobot.agent').warning('Remote graph started')
            return status()

    @app.post('/agent/stop')
    def stop():
        with operation():
            runtime.graph.stop()
            logging.getLogger('pyrobot.agent').warning('Remote graph stopped')
            return status()

    # Outermost middleware also attaches CORS headers to authentication errors.
    app.add_middleware(CORSMiddleware, allow_origins=origins or ['http://localhost:5173', 'http://127.0.0.1:5173'],
                       allow_methods=['GET', 'POST'], allow_headers=['Authorization', 'Content-Type'])
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--directory', type=Path, default=Path('artifacts/deployments'))
    parser.add_argument('--origin', action='append', help='Allowed Studio browser origin; repeat as needed')
    parser.add_argument('--certfile')
    parser.add_argument('--keyfile')
    args = parser.parse_args()
    if args.host not in ('127.0.0.1', 'localhost', '::1') and not (args.certfile and args.keyfile):
        parser.error('Remote listening requires --certfile and --keyfile. Alternatively use a localhost SSH tunnel.')
    token = os.environ.get('PYROBOT_AGENT_TOKEN', '')
    if len(token) < 32: parser.error('Set PYROBOT_AGENT_TOKEN to a random token of at least 32 characters')
    # Separate the agent bus from Studio on the same machine; never expose it on the LAN.
    runtime = Runtime(pub_endpoint='tcp://127.0.0.1:5595', sub_endpoint='tcp://127.0.0.1:5596')
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(create_app(token, args.directory, runtime, args.origin), host=args.host, port=args.port,
                ssl_certfile=args.certfile, ssl_keyfile=args.keyfile)


if __name__ == '__main__': main()
