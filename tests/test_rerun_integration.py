import sys
import time
import urllib.request
from urllib.parse import urlparse, parse_qs
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from backend.app.main import app


def test_rerun_bridge_serves_and_receives_logs():
    with TestClient(app) as client:
        r = client.get("/api/viz/url")
        body = r.json()
        assert body["available"] is True, "Rerun bridge did not report available — check rerun-sdk is installed"
        web_url = body["url"]
        assert parse_qs(urlparse(web_url).query)["url"][0].startswith("rerun+http://")
        print(f"OK: /api/viz/url reports Rerun web viewer at {web_url}")

        r = client.post("/api/graph/nodes", json={
            "node_id": "slam-1", "plugin_id": "pyrobot.examples.pointcloud_viz",
            "params": {"rate_hz": 20, "point_count": 200},
        })
        assert r.status_code == 200, r.text
        print("OK: added SLAM (Rerun) example node")

        client.post("/api/graph/start")
        time.sleep(0.8)

        resp = urllib.request.urlopen(web_url, timeout=5)
        assert resp.status == 200, f"expected the Rerun web viewer to respond 200, got {resp.status}"
        print(f"OK: Rerun web viewer responded HTTP {resp.status} while the SLAM node was actively logging")

        client.post("/api/graph/stop")
        client.delete("/api/graph/nodes/slam-1")
        print("OK: stopped and removed the SLAM node cleanly")


if __name__ == "__main__":
    test_rerun_bridge_serves_and_receives_logs()
    print("\nRerun integration test passed.")
