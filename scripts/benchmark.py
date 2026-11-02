"""Local synthetic-image benchmark. Never sends images to a model service."""

import io
import json
import platform
import resource
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from fastapi.testclient import TestClient
from PIL import Image
from app.config import Settings
from app.main import create_app


def wait(client, oid, statuses):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        op = client.get("/api/operations/" + oid).json()
        if op["status"] in statuses:
            return op
        if op["status"] == "failed":
            raise RuntimeError(str(op))
        time.sleep(0.02)
    raise TimeoutError("Batch did not finish")


def main():
    stream = io.BytesIO()
    Image.effect_noise((2400, 1600), 35).convert("RGB").save(stream, "JPEG", quality=88)
    blob = stream.getvalue()
    report = {
        "machine": platform.machine(),
        "python": platform.python_version(),
        "fixture": "10 copies of synthetic 2400x1600 noise JPEG; timing only, not photo quality evaluation",
        "input_bytes_each": len(blob),
    }
    with (
        tempfile.TemporaryDirectory() as d,
        TestClient(create_app(Settings(Path(d), "benchmark"))) as c,
    ):
        p = c.post("/api/projects", json={"name": "benchmark"}).json()
        pid = p["id"]
        t = time.perf_counter()
        upload = c.post(
            "/api/projects/" + pid + "/assets",
            files=[("files", (f"{i}.jpg", blob, "image/jpeg")) for i in range(10)],
        ).json()
        assert all(f["status"] == "succeeded" for f in upload["files"]), upload["files"]
        p = upload["project"]
        report["upload_decode_thumbnails_10_s"] = round(time.perf_counter() - t, 3)
        t = time.perf_counter()
        response = c.post(
            "/api/projects/" + pid + "/previews",
            json={
                "context_revision": p["revision"],
                "target_asset_ids": p["selected"],
                "preset_id": "warm",
            },
        )
        assert response.status_code == 200, response.text
        oid = response.json()["operation_id"]
        wait(c, oid, ("ready",))
        report["preview_s"] = round(time.perf_counter() - t, 3)
        t = time.perf_counter()
        c.post("/api/operations/" + oid + "/apply")
        op = wait(c, oid, ("succeeded", "partial_failed"))
        report["batch_10_s"] = round(time.perf_counter() - t, 3)
        report["batch_status"] = op["status"]
        t = time.perf_counter()
        data = c.get("/api/operations/" + oid + "/download.zip").content
        report["zip_s"] = round(time.perf_counter() - t, 3)
        report["zip_entries"] = len(zipfile.ZipFile(io.BytesIO(data)).namelist())
        report["process_peak_rss_mib"] = round(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024, 1
        )
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data/benchmark.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
