# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""
Bus abstraction for PyRobot Studio.

Keeps node/plugin code decoupled from the transport (ZeroMQ now, LCM
selectively for high-frequency local topics later — same as V3's hybrid
approach). Every message published through this layer carries a PRT
timestamp automatically, so plugin authors don't have to think about
timing at all unless they want fine control over capture-time stamping.
"""

from __future__ import annotations

import json
import threading
import logging
import queue
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Optional

from core.timing.clock import PRTClock, PRTTimestamp


class Subscription:
    """Idempotent cancellation handle returned by a bus subscription."""

    def __init__(self, cancel):
        self._cancel = cancel
        self._lock = threading.Lock()

    def close(self):
        with self._lock:
            cancel, self._cancel = self._cancel, None
        if cancel is not None:
            cancel()


@dataclass
class BusMessage:
    topic: str
    payload: dict
    timestamp: PRTTimestamp
    published_timestamp: Optional[PRTTimestamp] = None
    clock_domain: str = "session"
    schema: Optional[str] = None
    run_id: Optional[str] = None

    def to_wire(self) -> bytes:
        envelope = {
            "topic": self.topic,
            "payload": self.payload,
            "ts": self.timestamp.to_dict(),
            "published_ts": (self.published_timestamp or self.timestamp).to_dict(),
            "clock_domain": self.clock_domain,
            "schema": self.schema,
            "run_id": self.run_id,
        }
        return json.dumps(envelope).encode("utf-8")

    @staticmethod
    def from_wire(raw: bytes) -> "BusMessage":
        envelope = json.loads(raw.decode("utf-8"))
        return BusMessage(
            topic=envelope["topic"],
            payload=envelope["payload"],
            timestamp=PRTTimestamp.from_dict(envelope["ts"]),
            published_timestamp=PRTTimestamp.from_dict(envelope.get("published_ts", envelope["ts"])),
            clock_domain=envelope.get("clock_domain", "session"),
            schema=envelope.get("schema"),
            run_id=envelope.get("run_id"),
        )


class BusTransport(ABC):
    """Implemented per-backend (ZeroMQ first; LCM adapter can be dropped
    in later for topics that need it without touching plugin code)."""

    @abstractmethod
    def publish_raw(self, topic: str, raw: bytes) -> None: ...

    @abstractmethod
    def subscribe_raw(self, topic_pattern: str, callback: Callable[[str, bytes], None]) -> Optional[Subscription]: ...

    @abstractmethod
    def close(self) -> None: ...


class Bus:
    """
    The object plugins actually interact with. Wraps a BusTransport and
    a PRTClock so `bus.publish("camera/frame", {...})` automatically
    stamps and serializes.
    """

    def __init__(self, transport: BusTransport, clock: PRTClock):
        self._transport = transport
        self._clock = clock
        self._subscriptions: dict[str, list[Callable]] = {}
        self._lock = threading.Lock()

    def publish(self, topic: str, payload: dict, timestamp: Optional[PRTTimestamp] = None,
                *, published_timestamp=None, clock_domain="session", schema=None, run_id=None) -> BusMessage:
        ts = timestamp or self._clock.now()
        msg = BusMessage(topic=topic, payload=payload, timestamp=ts,
            published_timestamp=published_timestamp or self._clock.now(), clock_domain=clock_domain, schema=schema, run_id=run_id)
        self._transport.publish_raw(topic, msg.to_wire())
        return msg

    def subscribe(self, topic_pattern: str, callback: Callable[[BusMessage], None], *, exact: bool = False) -> Subscription:
        active = threading.Event()
        active.set()
        def _on_raw(topic: str, raw: bytes) -> None:
            if not active.is_set() or (exact and topic != topic_pattern):
                return
            if b'"__pyrobot_ready__"' in raw[:80]:
                return
            msg = BusMessage.from_wire(raw)
            callback(msg)

        handle = self._transport.subscribe_raw(topic_pattern, _on_raw)
        def cancel():
            active.clear()
            if handle is not None:
                handle.close()
        return Subscription(cancel)

    def wait_ready(self, topics, timeout=3.0):
        """Round-trip each exact route before releasing startup publications.

        Probes are retried because PUB/SUB subscription propagation is asynchronous.
        This is startup readiness, not a reliable-delivery promise for later data.
        """
        pending = set(topics)
        token = uuid.uuid4().hex
        raw = json.dumps({"__pyrobot_ready__": token}).encode()
        condition = threading.Condition()
        handles = []
        def acknowledge(topic, received):
            if received == raw:
                with condition:
                    pending.discard(topic)
                    condition.notify_all()
        try:
            for topic in pending.copy():
                handles.append(self._transport.subscribe_raw(topic, acknowledge))
            deadline = time.monotonic() + timeout
            while True:
                with condition:
                    outstanding = list(pending)
                if not outstanding:
                    return
                if time.monotonic() >= deadline:
                    raise TimeoutError("Message routes not ready: " + ", ".join(sorted(outstanding)))
                for topic in outstanding:
                    self._transport.publish_raw(topic, raw)
                with condition:
                    if pending:
                        condition.wait(.025)
        finally:
            for handle in handles:
                if handle is not None:
                    handle.close()

    def close(self) -> None:
        self._transport.close()


class ZmqTransport(BusTransport):
    """Sockets are created, used and closed exclusively by the I/O thread.

    The outbound queue is bounded; overload is reported to the publisher.
    Callbacks must be short: they execute on the I/O thread.
    """

    def __init__(self, broker_pub_endpoint="tcp://127.0.0.1:5555", broker_sub_endpoint="tcp://127.0.0.1:5556"):
        import zmq
        self._zmq = zmq
        self._endpoints = (broker_pub_endpoint, broker_sub_endpoint)
        self._outgoing = queue.Queue(maxsize=4096)
        self._callbacks = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._error = None
        self.last_progress = time.monotonic()
        self._thread = threading.Thread(target=self._loop, name="pyrobot-bus", daemon=True)
        self._thread.start()
        if not self._ready.wait(5):
            raise RuntimeError("Bus I/O thread failed to initialize")
        if self._error:
            raise RuntimeError("Bus initialization failed") from self._error

    def publish_raw(self, topic, raw):
        if self._stop.is_set():
            raise RuntimeError("Bus transport is closed")
        self._outgoing.put_nowait((topic.encode("utf-8"), raw))

    def subscribe_raw(self, topic_pattern, callback):
        token = object()
        with self._lock:
            if self._stop.is_set():
                raise RuntimeError("Bus transport is closed")
            self._callbacks[token] = (topic_pattern, callback)
        def cancel():
            with self._lock:
                self._callbacks.pop(token, None)
        return Subscription(cancel)

    def _loop(self):
        zmq = self._zmq
        pub = sub = None
        log = logging.getLogger("pyrobot.bus")
        try:
            ctx = zmq.Context.instance()
            pub, sub = ctx.socket(zmq.PUB), ctx.socket(zmq.SUB)
            pub.setsockopt(zmq.LINGER, 0)
            sub.setsockopt(zmq.LINGER, 0)
            pub.connect(self._endpoints[0])
            sub.connect(self._endpoints[1])
            patterns = set()
            self._ready.set()
            while not self._stop.is_set():
                self.last_progress = time.monotonic()
                with self._lock:
                    callbacks = list(self._callbacks.values())
                wanted = {pattern for pattern, _ in callbacks}
                for pattern in wanted - patterns:
                    sub.setsockopt(zmq.SUBSCRIBE, pattern.encode("utf-8"))
                for pattern in patterns - wanted:
                    sub.setsockopt(zmq.UNSUBSCRIBE, pattern.encode("utf-8"))
                patterns = wanted
                for _ in range(256):
                    try:
                        topic, raw = self._outgoing.get_nowait()
                    except queue.Empty:
                        break
                    pub.send_multipart([topic, raw])
                if not sub.poll(5):
                    continue
                topic_b, raw = sub.recv_multipart()
                topic = topic_b.decode("utf-8")
                for pattern, cb in callbacks:
                    if topic.startswith(pattern):
                        try:
                            cb(topic, raw)
                        except Exception:
                            log.exception("Bus callback failed for %s", topic)
        except Exception as exc:
            self._error = exc
            self._stop.set()
            log.exception("Bus I/O failed")
        finally:
            self._ready.set()
            if pub is not None:
                pub.close(0)
            if sub is not None:
                sub.close(0)

    def close(self):
        self._stop.set()
        with self._lock:
            self._callbacks.clear()
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=5)
