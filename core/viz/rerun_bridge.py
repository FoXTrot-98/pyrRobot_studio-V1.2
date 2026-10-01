# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""
Rerun bridge: PyRobot Studio's SLAM/3D visualization backend.

Rerun (https://rerun.io) handles the actual 3D rendering — point clouds,
poses, camera frustums, coordinate transforms over time — so this module
doesn't reimplement any of that. It just wires Rerun's Python SDK into
the rest of the system:

  1. `init_rerun()` starts a gRPC log stream (plugins call `rerun.log(...)`
     directly from anywhere, same process) and a web viewer HTTP server
     that renders it — no separate process, no desktop app required.
  2. The web viewer's URL is exposed via GET /api/viz/url so the frontend
     can embed it in an iframe (see frontend/src/components/RerunViewport.tsx).

Any plugin that wants a 3D view just does:
    import rerun as rr
    rr.log("world/points", rr.Points3D(points))
from inside its on_message/on_start — no plugin-specific wiring needed,
since rr.log() targets whatever recording was rr.init()'d in-process.
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlencode

logger = logging.getLogger("pyrobot.viz.rerun_bridge")

DEFAULT_GRPC_PORT = int(os.environ.get("PYROBOT_RERUN_GRPC_PORT", "9876"))
DEFAULT_WEB_PORT = int(os.environ.get("PYROBOT_RERUN_WEB_PORT", "9090"))

_state = {"web_url": None, "grpc_uri": None, "initialized": False}


def init_rerun(grpc_port: int = DEFAULT_GRPC_PORT, web_port: int = DEFAULT_WEB_PORT, app_id: str = "pyrobot-studio") -> str:
    """Idempotent: safe to call more than once (e.g. on backend hot-reload).
    Returns the web viewer URL the frontend should embed."""
    if _state["initialized"]:
        return _state["web_url"]

    import rerun as rr

    rr.init(app_id, spawn=False)
    grpc_uri = rr.serve_grpc(grpc_port=grpc_port)
    rr.serve_web_viewer(web_port=web_port, open_browser=False, connect_to=grpc_uri)

    # connect_to is used only for auto-opening a browser by the SDK. An embedded
    # viewer must receive the log server in its own URL, otherwise it opens Home.
    web_url = f"http://localhost:{web_port}/?{urlencode({'url': grpc_uri})}"
    _state.update(web_url=web_url, grpc_uri=grpc_uri, initialized=True)
    logger.info("rerun bridge live: grpc=%s web=%s", grpc_uri, web_url)
    return web_url


def get_web_url() -> str | None:
    return _state["web_url"]


def is_initialized() -> bool:
    return _state["initialized"]
