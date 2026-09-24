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

logger = logging.getLogger("pyrobot.bus.broker")

FRONTEND_ENDPOINT = os.environ.get("PYROBOT_BUS_PUB", "tcp://127.0.0.1:5555")
BACKEND_ENDPOINT = os.environ.get("PYROBOT_BUS_SUB", "tcp://127.0.0.1:5556")


def run_broker(frontend: str = FRONTEND_ENDPOINT, backend: str = BACKEND_ENDPOINT, stop_event=None, ready_event=None, errors=None) -> None:
    import zmq

    ctx = zmq.Context.instance()
    xsub = ctx.socket(zmq.XSUB)
    xpub = ctx.socket(zmq.XPUB)
    try:
        xsub.bind(frontend)
        xpub.bind(backend)
        if ready_event:
            ready_event.set()
        if stop_event is None:
            zmq.proxy(xsub, xpub)
        else:
            poller = zmq.Poller()
            poller.register(xsub, zmq.POLLIN)
            poller.register(xpub, zmq.POLLIN)
            while not stop_event.is_set():
                events = dict(poller.poll(20))
                if xsub in events:
                    xpub.send_multipart(xsub.recv_multipart())
                if xpub in events:
                    xsub.send_multipart(xpub.recv_multipart())
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        if errors is None:
            raise
        errors.append(exc)
    finally:
        if ready_event:
            ready_event.set()
        xsub.close(0)
        xpub.close(0)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_broker()
