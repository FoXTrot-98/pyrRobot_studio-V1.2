# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Disposable trusted-code test worker. Process isolation is not a security sandbox."""
import json
import logging
from pathlib import Path
import sys
import time
import traceback
from core.runtime.plugin_registry import PluginRegistry
from core.runtime.graph import NodeGraph
from core.bus.base import Bus, BusTransport, Subscription, BusMessage
from core.timing.clock import PRTClock, ClockAuthority, discipline_from_beacon
from core.messages import validate_payload


def main():
    directory = Path(sys.argv[1])
    outputs, logs = [], []
    class TextCapture:
        def write(self, value):
            if value.strip() and len(logs) < 30: logs.append(value[:500])
            return len(value)
        def flush(self): pass
    sys.stdout = sys.stderr = TextCapture()
    class Capture(BusTransport):
        def publish_raw(self, topic, raw):
            if len(raw) > 32768: raise ValueError('Test output exceeds 32 KiB')
            if len(outputs) >= 20: raise ValueError('Test emitted more than 20 messages')
            outputs.append(json.loads(raw))
        def subscribe_raw(self, pattern, callback): return Subscription(lambda: None)
        def close(self): pass
    class LogCapture(logging.Handler):
        def emit(self, record):
            if len(logs) < 30: logs.append(self.format(record)[:500])
    logging.getLogger().addHandler(LogCapture())
    logging.getLogger().setLevel(logging.INFO)
    node = None
    report = {'ok': False}
    try:
        registry = PluginRegistry()
        registry.scan_directory(directory)
        if len(registry) != 1: raise ValueError('Source must declare exactly one plugin')
        entry = next(iter(registry._entries.values()))
        manifest = entry.manifest
        for ports in (manifest.inputs, manifest.outputs):
            if len({p.name for p in ports}) != len(ports): raise ValueError('Duplicate port names')
        if not manifest.outputs: raise ValueError('Test requires an output port')
        params = {p.name: p.default for p in manifest.params}
        NodeGraph._validate_params(manifest, params)
        authority = ClockAuthority(lambda *_: None)
        authority.start_session()
        clock = PRTClock('builder-test')
        discipline_from_beacon(clock, authority.emit_beacon())
        bus = Bus(Capture(), clock)
        node = entry.node_class(node_id='builder_test', bus=bus, params=params)
        node.validate_configuration()
        node.start()
        sample = json.loads((directory / 'input.json').read_text(encoding='utf-8'))
        for port in manifest.inputs:
            payload = validate_payload(port.schema, sample)
            node._receive(port.name, BusMessage(topic='', payload=payload, timestamp=bus._clock.now(), schema=port.schema))
        time.sleep(.35)
        if node.state == 'failed': raise ValueError(node.error)
        node.stop()
        if not outputs: raise ValueError('No output received; supply sample data or emit during the test')
        report = {'ok': True, 'manifest': manifest.to_dict()}
    except Exception:
        report['error'] = traceback.format_exc()[-4000:]
    finally:
        if node:
            try: node.stop()
            except Exception: report.update(ok=False, error=traceback.format_exc()[-4000:])
        report.update(outputs=outputs[:10], logs=logs)
        encoded = json.dumps(report)
        if len(encoded.encode()) > 120000:
            encoded = json.dumps({'ok': False, 'error': 'Test report too large; reduce sample/output size'})
        (directory / 'result.json').write_text(encoded, encoding='utf-8')


if __name__ == '__main__': main()
