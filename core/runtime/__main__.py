# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""python -m core.runtime validate|run project.pyrobot.json"""
import argparse
import logging
import math
from pathlib import Path
import signal
import sys
import threading
import time

from core.bus.base import BusTransport, Subscription, Bus
from core.timing.clock import PRTClock
from .plugin_registry import PluginRegistry
from .project import ProjectDocument, prepare_project
from .session import Runtime, DEFAULT_PLUGIN_DIRS


class ValidationTransport(BusTransport):
    """Validate topology without opening sockets or starting devices."""
    def publish_raw(self, topic, raw):
        raise RuntimeError("Publishing is unavailable during project validation")

    def subscribe_raw(self, pattern, callback):
        return Subscription(lambda: None)

    def close(self):
        pass


def positive_seconds(value):
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("Duration must be a finite positive number")
    return seconds


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate or run PyRobot projects without Studio")
    parser.add_argument("command", choices=("validate", "run"))
    parser.add_argument("project", type=Path)
    parser.add_argument("--plugin-dir", type=Path, action="append", default=[], help="Additional trusted plugin directory")
    parser.add_argument("--duration", type=positive_seconds, help="Stop after this many seconds (run only)")
    parser.add_argument("--viz", action="store_true", help="Start the Rerun web viewer (run only)")
    args = parser.parse_args(argv)
    if args.command == "validate" and (args.duration or args.viz):
        parser.error("--duration and --viz apply only to run")
    logging.basicConfig(level=logging.INFO)
    try:
        document = ProjectDocument.model_validate_json(args.project.read_text(encoding="utf-8-sig"))
        directories = (*DEFAULT_PLUGIN_DIRS, *args.plugin_dir)
        if args.command == "validate":
            registry = PluginRegistry()
            for directory in directories:
                registry.scan_directory(directory)
            bus = Bus(ValidationTransport(), PRTClock("validation"))
            graph, _ = prepare_project(document, bus, registry)
            diagnostics = graph.preflight()
            graph.close()
            bus.close()
            if diagnostics:
                raise ValueError("Preflight failed: " + "; ".join(d["message"] for d in diagnostics))
            print(f"Valid project: {document.name} ({len(document.nodes)} nodes)")
            return 0

        stop = threading.Event()
        previous = {}
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, lambda *_: stop.set())
        try:
            with Runtime(plugin_dirs=directories) as runtime:
                runtime.load_project(document)
                if args.viz:
                    from core.viz.rerun_bridge import init_rerun
                    print(f"Rerun viewer: {init_rerun()}")
                runtime.graph.start()
                print(f"Running: {document.name}. Press Ctrl+C to stop.", flush=True)
                deadline = time.monotonic() + args.duration if args.duration else None
                while not stop.wait(.1):
                    failed = [n for n in runtime.graph.to_dict()["nodes"] if n["state"] == "failed"]
                    if failed:
                        raise RuntimeError("Node failure: " + "; ".join(f"{n['node_id']}: {n['error']}" for n in failed))
                    if deadline is not None and time.monotonic() >= deadline:
                        break
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
        print("Project stopped; runtime resources released.")
        return 0
    except Exception as exc:
        print(f"PyRobot: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
