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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pyrobot.backend")

from fastapi.middleware.cors import CORSMiddleware

@asynccontextmanager
async def lifespan(app):
    startup()
    try:
        yield
    finally:
        shutdown()


app = FastAPI(title="PyRobot Studio Backend", lifespan=lifespan)
runtime = Runtime()

def serialized(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with runtime.lock:
            return fn(*args, **kwargs)
    return wrapped

# The Studio frontend (Vite dev server) runs on a different port than the
# backend, so the browser needs CORS clearance for both REST calls and the
# /ws/bus WebSocket. Wide open for local development; tighten before any
# non-localhost deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    runtime.close()


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


@app.get("/api/robot/setup")
@serialized
def robot_setup_defaults():
    return {"robot_urdf": runtime.robot_xml, "robot_config": runtime.graph.robot_config.model_dump(),
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
        return inspect_robot(request.robot_urdf)
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
        await websocket.accept()
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
    await websocket.accept()
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
