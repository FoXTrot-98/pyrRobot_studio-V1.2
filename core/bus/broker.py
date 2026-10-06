# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""
Bus broker: a standalone XSUB/XPUB proxy that every node/plugin connects
to. This is what makes multi-process pub/sub actually work — individual
ZmqTransport instances (see base.py) connect to this broker rather than
binding directly to each other.

Run standalone:
    python -m core.bus.broker

Or embed in the backend server process at startup.
"""

from __future__ import annotations

import logging
import os
import threading
import uuid

logger = logging.getLogger("pyrobot.bus.broker")

FRONTEND_ENDPOINT = os.environ.get("PYROBOT_BUS_PUB", "tcp://127.0.0.1:5555")
BACKEND_ENDPOINT = os.environ.get("PYROBOT_BUS_SUB", "tcp://127.0.0.1:5556")


def run_broker(frontend: str = FRONTEND_ENDPOINT, backend: str = BACKEND_ENDPOINT, stop_event=None, ready_event=None, errors=None) -> None:
    import zmq

    ctx = zmq.Context.instance()
    xsub = ctx.socket(zmq.XSUB)
    xpub = ctx.socket(zmq.XPUB)
    control = None
    controller = None
    finished = threading.Event()
    try:
        xsub.bind(frontend)
        xpub.bind(backend)
        if ready_event:
            ready_event.set()
        if stop_event is None:
            zmq.proxy(xsub, xpub)
        else:
            # Keep packet forwarding in libzmq, as in standalone mode. A Python
            # recv/send/poll loop competes with mapping and browser serialization
            # for the GIL on every packet, building up stale control traffic.
            address = f"inproc://pyrobot-broker-stop-{uuid.uuid4().hex}"
            control = ctx.socket(zmq.PAIR)
            control.bind(address)

            def request_stop():
                sender = ctx.socket(zmq.PAIR)
                try:
                    sender.connect(address)
                    while not finished.is_set():
                        if stop_event.wait(.02):
                            sender.send(b"TERMINATE")
                            # Keep the pipe alive until the proxy consumes the
                            # command, including an immediate startup stop.
                            finished.wait()
                            return
                finally:
                    sender.close(0)

            controller = threading.Thread(target=request_stop, name="pyrobot-broker-stop", daemon=True)
            controller.start()
            zmq.proxy_steerable(xsub, xpub, control=control)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        if errors is None:
            raise
        errors.append(exc)
    finally:
        finished.set()
        if controller is not None:
            controller.join(timeout=1)
        if control is not None:
            control.close(0)
        if ready_event:
            ready_event.set()
        xsub.close(0)
        xpub.close(0)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_broker()
