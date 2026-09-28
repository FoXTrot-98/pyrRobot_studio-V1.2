"""
PyRobot Studio backend.

Run with:
    uvicorn backend.app.main:app --port 8000

Endpoints:
    GET    /api/plugins                  -> list registered plugin manifests
    POST   /api/robot/urdf               -> upload a .urdf file, parse it, return link names
    GET    /api/robot/links              -> link names of the currently loaded robot
    GET    /api/graph                    -> current graph state (nodes + connections)
    POST   /api/graph/nodes              -> add a node instance
    DELETE /api/graph/nodes/{node_id}    -> remove a node instance
    POST   /api/graph/connections        -> connect an output port to an input port
    POST   /api/graph/start              -> start running the graph
    POST   /api/graph/stop               -> stop the graph
    WS     /ws/bus                       -> live stream of every bus message (for UI node-graph animation / debug console)
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import subprocess
import uuid
from contextlib import asynccontextmanager, suppress
from functools import wraps
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from core.viz.rerun_bridge import init_rerun, get_web_url
from core.runtime.session import Runtime
from core.runtime.graph import GraphError
from core.runtime.project import ProjectDocument, Position
from core.simulation.config import RobotConfiguration
from core.runtime.robot_setup import SetupRequest, inspect_robot, draft_project, revision, EXAMPLE
from core.simulation.webots_examples import PROFILES, example_project
from core.runtime.plugin_builder import Builder, Draft, TestRequest, generate
from core.messages import SCHEMAS
from core.urdf.builder import Model as BuilderModel, import_obj, preview as model_preview, bundle as model_bundle
from core.urdf.cad import import_step
from core.urdf.assets import Assets, builder_package, read_builder_bundle
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pyrobot.backend")

from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .security import StudioSecurity, studio_origins
import os

@asynccontextmanager
async def lifespan(app):
    startup()
    try:
        yield
    finally:
        shutdown()


app = FastAPI(title="PyRobot Studio Backend", lifespan=lifespan)
runtime = Runtime()
plugin_builder = Builder()

def serialized(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with runtime.lock:
            return fn(*args, **kwargs)
    return wrapped

# Explicit browser origins and hosts; local-only unless authenticated access
# is configured. StudioSecurity also checks WebSocket origins and credentials.
app.add_middleware(StudioSecurity)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=[h.strip() for h in os.environ.get(
    'PYROBOT_STUDIO_HOSTS', 'localhost,127.0.0.1,[::1],testserver').split(',')])
app.add_middleware(
    CORSMiddleware,
    allow_origins=studio_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

def startup() -> None:
    runtime.open()
    try:
        init_rerun()
    except Exception as exc:
        logger.error("Failed to start Rerun bridge: %s", exc)


def shutdown():
    plugin_builder.close()
    runtime.close()


@app.get('/api/plugin-builder/catalog')
def builder_catalog():
    return {'schemas': {key: value.model_json_schema() for key, value in SCHEMAS.items()},
            'types': ['json', 'image', 'number', 'string', 'bool', 'pose', 'imu', 'pointcloud']}


@app.post('/api/plugin-builder/generate')
def builder_generate(draft: Draft):
    try: return {'source': generate(draft)}
    except (ValueError, GraphError) as exc: raise HTTPException(422, str(exc)) from exc


@app.post('/api/plugin-builder/tests')
def builder_test(request: TestRequest):
    try: return plugin_builder.start(request)
    except (ValueError, SyntaxError) as exc: raise HTTPException(422, str(exc)) from exc


@app.get('/api/plugin-builder/tests/{test_id}')
def builder_test_status(test_id: str):
    try: return plugin_builder.status(test_id)
    except KeyError as exc: raise HTTPException(404, 'Unknown test') from exc


@app.delete('/api/plugin-builder/tests/{test_id}')
def builder_cancel_test(test_id: str):
    try: return plugin_builder.cancel(test_id)
    except KeyError as exc: raise HTTPException(404, 'Unknown test') from exc


@app.post('/api/plugin-builder/tests/{test_id}/install')
@serialized
def builder_install(test_id: str):
    if runtime.graph.to_dict()['running']: raise HTTPException(409, 'Stop the graph before installing plugins')
    try: return plugin_builder.install(test_id, runtime.registry)
    except KeyError as exc: raise HTTPException(404, 'Unknown test') from exc
    except (ValueError, FileExistsError) as exc: raise HTTPException(409, str(exc)) from exc


@app.get("/api/viz/url")
def get_viz_url():
    url = get_web_url()
    if url is None:
        return {"available": False, "url": None}
    return {"available": True, "url": url}


# -- plugins ----------------------------------------------------------

@app.get("/api/plugins")
@serialized
def list_plugins():
    return {"plugins": runtime.registry.list_manifests()}


# -- robot / URDF ----------------------------------------------------------

class ObjImportRequest(BaseModel):
    text: str = Field(max_length=4*1024*1024)
    split: bool = True


class ModelPreviewRequest(BaseModel):
    model: BuilderModel
    positions: dict[str, float] = Field(default_factory=dict)


@app.post('/api/model-builder/import-obj')
def builder_import_obj(request: ObjImportRequest):
    try: return import_obj(request.text, request.split).model_dump()
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@app.post('/api/model-builder/import-step')
async def builder_import_step(file: UploadFile, deflection: float = 0.5, angle: float = 0.5):
    suffix = Path(file.filename or '').suffix.lower()
    if suffix not in ('.step', '.stp'):
        raise HTTPException(400, 'Expected a .step or .stp file')
    data = await file.read(64 * 1024 * 1024 + 1)
    if len(data) > 64 * 1024 * 1024:
        raise HTTPException(413, 'STEP file exceeds 64 MiB')
    try:
        model = await run_in_threadpool(import_step, data, filename=file.filename or 'robot.step', deflection=deflection, angle=angle)
        return model.model_dump()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        logger.exception('STEP import failed')
        raise HTTPException(422, f'Failed to import STEP: {exc}') from exc


@app.post('/api/model-builder/preview')
def builder_preview_model(request: ModelPreviewRequest):
    try: return model_preview(request.model, request.positions)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@app.post('/api/model-builder/document')
def builder_check_document(model: BuilderModel):
    return model.model_dump()


@app.post('/api/model-builder/export')
def builder_export_model(model: BuilderModel):
    try:
        archive, _, _ = model_bundle(model)
        return Response(archive, media_type='application/zip', headers={'Content-Disposition':'attachment; filename="robot-model.zip"'})
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@app.post('/api/model-builder/validate')
def builder_validate_model(model: BuilderModel):
    try:
        _, xml, warnings = model_bundle(model)
        return {'urdf':xml, 'warnings':warnings}
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@app.post('/api/model-builder/setup')
def builder_setup_package(model: BuilderModel):
    try: return builder_package(model)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@app.post('/api/robot/setup/bundle')
async def inspect_builder_bundle(file: UploadFile):
    data = await file.read(8*1024*1024+1)
    try: return read_builder_bundle(data)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc

@app.post("/api/robot/urdf")
async def upload_urdf(file: UploadFile):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".urdf", ".xacro"):
        raise HTTPException(400, "Expected a .urdf or .xacro file")
    contents = await file.read(4 * 1024 * 1024 + 1)
    if len(contents) > 4 * 1024 * 1024:
        raise HTTPException(413, "Robot description exceeds 4 MiB")
    try:
        xml = contents.decode("utf-8-sig")
        if suffix == ".xacro":
            with tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "robot.xacro"
                source.write_text(xml, encoding="utf-8")
                result = subprocess.run(["xacro", str(source)], capture_output=True, text=True, timeout=30)
                if result.returncode:
                    raise ValueError(result.stderr)
                xml = result.stdout
        return runtime.set_robot(xml)
    except Exception as exc:
        raise HTTPException(400, f"Failed to load robot: {exc}") from exc


@app.get("/api/robot/links")
@serialized
def get_robot_links():
    info = runtime.robot_info()
    if info is None:
        raise HTTPException(404, "No robot URDF loaded")
    return info


# -- graph ----------------------------------------------------------

class InspectRobotRequest(BaseModel):
    robot_urdf: str = Field(min_length=1, max_length=4*1024*1024)
    robot_assets: Assets = Field(default_factory=dict)


@app.get("/api/robot/setup")
@serialized
def robot_setup_defaults():
    return {"robot_urdf": runtime.robot_xml, "robot_config": runtime.graph.robot_config.model_dump(),
            "robot_assets": {k:v.model_dump() for k,v in runtime.robot.assets.items()} if runtime.robot else {},
            "name": runtime.name, "revision": revision(runtime), "node_count": len(runtime.graph.nodes),
            "reference_urdf": (EXAMPLE/"robot.urdf").read_text(encoding="utf-8")}


@app.get("/api/examples/webots")
def webots_examples():
    return [{"id":key,"title":value["title"],"actions":value["actions"],"world":value["world"]} for key,value in PROFILES.items()]


@app.get("/api/examples/webots/{profile}")
def webots_example(profile: str):
    if profile not in PROFILES: raise HTTPException(404,"Unknown Webots example")
    return example_project(profile)


@app.post("/api/robot/setup/inspect")
def inspect_setup_robot(request: InspectRobotRequest):
    try:
        return inspect_robot(request.robot_urdf, request.robot_assets)
    except Exception as exc:
        raise HTTPException(400, f"Cannot preview this URDF: {exc}") from exc


@app.post("/api/robot/setup/preview")
@serialized
def preview_robot_setup(request: SetupRequest):
    try:
        _, summary = draft_project(runtime, request)
        return summary
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/robot/setup/apply")
@serialized
def apply_robot_setup(request: SetupRequest):
    try:
        document, _ = draft_project(runtime, request)
        return runtime.load_project(document)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc

class AddNodeRequest(BaseModel):
    node_id: str
    plugin_id: str
    params: dict = Field(default_factory=dict)
    urdf_link: Optional[str] = None


class ConnectRequest(BaseModel):
    from_node: str
    from_port: str
    to_node: str
    to_port: str


class UpdateParamsRequest(BaseModel):
    params: dict = Field(default_factory=dict)


@app.get("/api/graph")
@serialized
def get_graph():
    return runtime.graph.to_dict()


@app.get("/api/graph/preflight")
@serialized
def graph_preflight():
    diagnostics = runtime.graph.preflight()
    return {"ready": not diagnostics, "diagnostics": diagnostics}


@app.patch("/api/project/robot-config")
def update_robot_config(configuration: RobotConfiguration):
    try:
        return runtime.set_robot_config(configuration)
    except (GraphError, ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/graph/nodes")
@serialized
def add_node(req: AddNodeRequest):
    try:
        runtime.add_node(req.node_id, req.plugin_id, req.params, req.urdf_link)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except GraphError as e:
        raise HTTPException(400, str(e))
    return runtime.graph.to_dict()


@app.patch("/api/graph/nodes/{node_id}/params")
@serialized
def update_node_params(node_id: str, req: UpdateParamsRequest):
    try:
        runtime.graph.update_node_params(node_id, req.params)
    except GraphError as e:
        raise HTTPException(400, str(e))
    return runtime.graph.to_dict()


@app.delete("/api/graph/nodes/{node_id}")
@serialized
def remove_node(node_id: str):
    try:
        runtime.remove_node(node_id)
    except GraphError as e:
        raise HTTPException(404, str(e))
    return runtime.graph.to_dict()


@app.post("/api/graph/connections")
@serialized
def connect(req: ConnectRequest):
    try:
        runtime.graph.connect(req.from_node, req.from_port, req.to_node, req.to_port)
    except GraphError as e:
        raise HTTPException(400, str(e))
    return runtime.graph.to_dict()


@app.post("/api/graph/start")
@serialized
def start_graph():
    try:
        runtime.graph.start()
    except GraphError as exc:
        raise HTTPException(400, str(exc)) from exc
    return runtime.graph.to_dict()


@app.post("/api/graph/stop")
@serialized
def stop_graph():
    try:
        runtime.graph.stop()
    except GraphError as exc:
        raise HTTPException(400, str(exc)) from exc
    return runtime.graph.to_dict()


@app.delete("/api/graph/connections")
@serialized
def disconnect(req: ConnectRequest):
    try:
        runtime.graph.disconnect(**req.model_dump())
    except GraphError as exc:
        raise HTTPException(400, str(exc)) from exc
    return runtime.graph.to_dict()


class BindingRequest(BaseModel):
    urdf_link: str


@app.patch("/api/graph/nodes/{node_id}/binding")
@serialized
def update_binding(node_id: str, req: BindingRequest):
    try:
        runtime.bind_node(node_id, req.urdf_link)
    except GraphError as exc:
        raise HTTPException(400, str(exc)) from exc
    return runtime.graph.to_dict()


class ExportRequest(BaseModel):
    name: str = Field(default="Untitled robot", min_length=1, max_length=200)
    positions: dict[str, Position] = Field(default_factory=dict)


@app.get("/api/project")
@serialized
def get_project():
    return runtime.project_info()


@app.post("/api/project/export")
@serialized
def save_project(req: ExportRequest):
    try:
        return runtime.export(req.name, {k: v.model_dump() for k, v in req.positions.items()})
    except GraphError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/project/import")
@serialized
def open_project(document: ProjectDocument):
    if runtime.graph.to_dict()["running"]:
        raise HTTPException(409, "Stop the graph before opening another project")
    try:
        return runtime.load_project(document)
    except Exception as exc:
        raise HTTPException(400, f"Project was not opened: {exc}") from exc


# -- live bus stream for the UI ------------------------------------------------

@app.websocket("/ws/control/{node_id}")
async def ws_control(websocket: WebSocket, node_id: str, run_id: str):
    from plugins.user.keyboard_teleop import KeyboardTeleop
    owner = uuid.uuid4().hex
    node = None
    try:
        with runtime.lock:
            instance = runtime.graph.nodes.get(node_id)
            if instance and instance.plugin_id == KeyboardTeleop.manifest.id and runtime.graph.to_dict()["running"] and run_id == runtime.graph.run_id:
                node = instance.node_obj
                node.acquire(owner)
        if node is None:
            await websocket.close(code=1008)
            return
        await websocket.accept(subprotocol="pyrobot" if "pyrobot" in websocket.scope.get("subprotocols", []) else None)
        while True:
            packet = await asyncio.wait_for(websocket.receive_json(), timeout=5.)
            if not node._running or node.run_id != run_id:
                break
            node.accept_keys(owner, packet.get("sequence"), packet.get("keys"))
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    except (ValueError, TypeError, AttributeError):
        with suppress(RuntimeError):
            await websocket.close(code=1008)
    finally:
        if node is not None:
            node.release(owner)
        with suppress(RuntimeError):
            await websocket.close()

@app.websocket("/ws/bus")
async def ws_bus(websocket: WebSocket):
    await websocket.accept(subprotocol="pyrobot" if "pyrobot" in websocket.scope.get("subprotocols", []) else None)
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue(maxsize=128)
    active = True

    def enqueue(payload):
        if not active:
            return
        if queue.full():
            queue.get_nowait()  # UI previews favor fresh data over stale backlog.
        queue.put_nowait(payload)

    def on_message(msg):
        if active and not loop.is_closed():
            loop.call_soon_threadsafe(enqueue, {
                "topic": msg.topic, "payload": msg.payload, "ts": msg.timestamp.to_dict(),
                "published_ts": (msg.published_timestamp or msg.timestamp).to_dict(),
                "clock_domain": msg.clock_domain, "schema": msg.schema,
                "run_id": msg.run_id,
            })

    handle = runtime.bus.subscribe("", on_message)

    async def send_messages():
        while True:
            await websocket.send_json(await queue.get())

    async def receive_disconnect():
        while True:
            await websocket.receive_text()

    tasks = [asyncio.create_task(send_messages()), asyncio.create_task(receive_disconnect())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        active = False
        handle.close()
        for task in tasks:
            task.cancel()
        with suppress(asyncio.CancelledError):
            await asyncio.gather(*tasks, return_exceptions=True)
