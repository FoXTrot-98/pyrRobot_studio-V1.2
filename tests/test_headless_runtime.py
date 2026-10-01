# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.runtime.project import ProjectDocument
from core.runtime.session import Runtime

EXAMPLE = ROOT / "examples/imu-demo.pyrobot.json"


class HeadlessTests(unittest.TestCase):
    def test_runtime_executes_and_releases_broker_for_next_session(self):
        document = ProjectDocument.model_validate_json(EXAMPLE.read_text())
        for _ in range(2):
            with Runtime() as runtime:
                runtime.load_project(document)
                self.assertFalse(runtime.graph.to_dict()["running"])
                runtime.graph.start()
                sink = runtime.graph.nodes["logger"].node_obj
                deadline = time.monotonic() + 3
                while sink.count < 5 and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertGreaterEqual(sink.count, 5)
                runtime.graph.stop()
                self.assertEqual(runtime.export().name, document.name)
            self.assertIsNone(runtime.bus)

    def test_runtime_has_no_fastapi_import(self):
        result = subprocess.run([sys.executable, "-c",
            "from core.runtime.session import Runtime; import sys; assert 'fastapi' not in sys.modules; assert 'backend.app.main' not in sys.modules"],
            cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "core.runtime", *map(str, args)],
            cwd=ROOT, env=dict(os.environ, PYTHONUTF8="1"), capture_output=True,
            text=True, encoding="utf-8", timeout=15)

    def test_cli_validation_does_not_need_free_broker_ports(self):
        with Runtime():
            result = self.run_cli("validate", EXAMPLE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Valid project", result.stdout)

    def test_cli_runs_and_stops_saved_project(self):
        result = self.run_cli("run", EXAMPLE, "--duration", "0.3")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Running: IMU demo", result.stdout)
        self.assertIn("runtime resources released", result.stdout)

    def test_invalid_project_returns_nonzero(self):
        with tempfile.TemporaryDirectory(prefix="pyrobot-headless-") as directory:
            path = Path(directory) / "invalid.json"
            data = json.loads(EXAMPLE.read_text())
            data["nodes"][0]["plugin_version"] = "999"
            path.write_text(json.dumps(data), encoding="utf-8")
            result = self.run_cli("validate", path)
            self.assertEqual(result.returncode, 1)
            self.assertIn("requires version 999", result.stderr)


if __name__ == "__main__":
    unittest.main()
