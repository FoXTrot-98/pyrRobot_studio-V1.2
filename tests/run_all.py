# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Run each test script in isolation, with a timeout and portable temp paths."""
import os
from pathlib import Path
import subprocess
import sys
import socket


def main():
    root = Path(__file__).resolve().parents[1]
    failed = []
    env = dict(os.environ, PYTHONUTF8="1")
    # Keep tests separate from an already-running user's Studio session.
    sockets = [socket.socket() for _ in range(4)]
    try:
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        ports = [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()
    env.update(PYROBOT_BUS_PUB=f"tcp://127.0.0.1:{ports[0]}",
               PYROBOT_BUS_SUB=f"tcp://127.0.0.1:{ports[1]}",
               PYROBOT_RERUN_GRPC_PORT=str(ports[2]), PYROBOT_RERUN_WEB_PORT=str(ports[3]))
    for test in sorted((root / "tests").glob("test_*.py")):
        try:
            result = subprocess.run([sys.executable, str(test)], cwd=root, env=env,
                                    capture_output=True, text=True, encoding="utf-8", timeout=60)
            print(f"{'PASS' if result.returncode == 0 else 'FAIL'} {test.name}", flush=True)
            for line in result.stdout.splitlines():
                if line.startswith("SKIP:"):
                    print(f"  {line}", flush=True)
            if result.returncode:
                failed.append(test.name)
                print(result.stdout[-5000:] + result.stderr[-5000:], flush=True)
        except subprocess.TimeoutExpired:
            failed.append(test.name)
            print(f"FAIL {test.name}: exceeded 60 seconds", flush=True)
    print(f"Finished: {len(failed)} failed test scripts", flush=True)
    return bool(failed)


if __name__ == "__main__":
    sys.exit(main())
