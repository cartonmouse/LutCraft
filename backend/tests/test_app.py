import asyncio
import hashlib
import io
import json
import time
import zipfile
from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageCms
from app.config import Settings
from app.main import create_app
from app.schemas import Plan, Recipe, Adjustment
from app.recipes import merge_recipe
from app.imaging import render, inspect


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(tmp_path, "test-secret", agent_runtime="direct"))) as c:
        yield c


def photo(color=(80, 120, 180), mode="RGB", size=(120, 80), **kwargs):
    out = io.BytesIO()
    Image.new(mode, size, color).save(out, format=kwargs.pop("format", "PNG"), **kwargs)
    return out.getvalue()


def create(c, n=3):
    p = c.post("/api/projects", json={"name": "测试影集"}).json()
    r = c.post(
        f"/api/projects/{p['id']}/assets",
        files=[
            ("files", (f"{i}.png", photo((60 + i * 20, 120, 170)), "image/png"))
            for i in range(n)
        ],
    )
    assert r.status_code == 200, r.text
    assert all(i["status"] == "succeeded" for i in r.json()["files"]), r.text
    return r.json()["project"]


def wait(c, oid, statuses=("ready", "failed", "stale")):
    for _ in range(150):
        op = c.get("/api/operations/" + oid).json()
        if op["status"] in statuses:
            return op
        time.sleep(0.02)
    pytest.fail(str(op))


def preview(c, p, ids=None, adjustments=None, preset=None):
    r = c.post(
        f"/api/projects/{p['id']}/previews",
        json={
            "context_revision": p["revision"],
            "target_asset_ids": ids or p["selected"],
            "adjustments": adjustments or [],
            "preset_id": preset,
        },
    )
    assert r.status_code == 200, r.text
    op = wait(c, r.json()["operation_id"])
    assert op["status"] == "ready", op
    return op


def test_upload_preview_apply_download_isolation(client):
    c = client
    p = create(c)
    aid = p["assets"][0]["id"]
    pid = p["id"]
    before = c.get(f"/api/assets/{aid}/files/original").content
    op = preview(c, p, ids=[p["assets"][0]["id"], p["assets"][2]["id"]], preset="warm")
    assert len(op["items"]) == 2
    assert c.get(op["preview_url"]).headers["content-type"] == "image/png"
    assert c.post(f"/api/operations/{op['id']}/apply").status_code == 200
    assert c.post(f"/api/operations/{op['id']}/apply").status_code == 200
    op = wait(c, op["id"], ("succeeded", "failed", "partial_failed"))
    assert op["status"] == "succeeded", op
    p = c.get("/api/projects/" + pid).json()
    assert [a["revision"] for a in p["assets"]] == [1, 0, 1]
    assert c.get(f"/api/assets/{aid}/files/original").content == before
    z = zipfile.ZipFile(io.BytesIO(c.get(op["download_url"]).content))
    assert len(z.namelist()) == 3
    assert len(json.loads(z.read("manifest.json"))["items"]) == 2
    with TestClient(c.app) as other:
        assert other.get("/api/projects/" + pid).status_code == 404
        assert other.get(f"/api/assets/{aid}/files/current").status_code == 404
        assert other.get(op["download_url"]).status_code == 404


def test_continuation_selection_and_stale(client):
    c = client
    p = create(c)
    inc = [{"field": "warmth", "op": "add", "value": 0.1}]
    first = preview(c, p, adjustments=inc)
    p = c.get("/api/projects/" + p["id"]).json()
    second = preview(c, p, adjustments=inc)
    assert second["items"][0]["recipe"]["warmth"] == 0.2
    assert c.post("/api/operations/" + first["id"] + "/apply").status_code == 409
    p = c.get("/api/projects/" + p["id"]).json()
    r = c.patch(
        "/api/projects/" + p["id"] + "/workspace",
        json={
            "context_revision": p["revision"],
            "selected_asset_ids": [p["assets"][1]["id"]],
            "viewed_asset_id": p["viewed"],
        },
    )
    assert r.status_code == 200
    assert c.post("/api/operations/" + second["id"] + "/apply").status_code == 409
    assert all(a["revision"] == 0 for a in r.json()["assets"])


def test_partial_failure_retry(client, monkeypatch):
    c = client
    p = create(c)
    op = preview(c, p, preset="warm")
    import app.service as service

    real = service.imaging.render

    def failing(source, target, *args):
        if p["assets"][1]["id"] in str(target):
            raise RuntimeError("injected render failure")
        return real(source, target, *args)

    monkeypatch.setattr(service.imaging, "render", failing)
    c.post("/api/operations/" + op["id"] + "/apply")
    op = wait(c, op["id"], ("partial_failed", "failed", "succeeded"))
    assert op["status"] == "partial_failed"
    state = c.get("/api/projects/" + p["id"]).json()
    assert [a["revision"] for a in state["assets"]] == [1, 0, 1]
    manifest = json.loads(
        zipfile.ZipFile(io.BytesIO(c.get(op["download_url"]).content)).read(
            "manifest.json"
        )
    )
    assert [i["status"] for i in manifest["items"]] == [
        "succeeded",
        "failed",
        "succeeded",
    ]
    monkeypatch.setattr(service.imaging, "render", real)
    response = c.post("/api/operations/" + op["id"] + "/retry")
    assert response.status_code == 200, response.text
    new = wait(c, response.json()["operation_id"])
    assert [i["ordinal"] for i in new["items"]] == [2]
    c.post("/api/operations/" + new["id"] + "/apply")
    wait(c, new["id"], ("succeeded",))
    assert [
        a["revision"] for a in c.get("/api/projects/" + p["id"]).json()["assets"]
    ] == [1, 1, 1]


def test_model_unconfigured_and_memory(client):
    c = client
    p = create(c, 1)
    body = {
        "context_revision": p["revision"],
        "request_id": "missing-config-01",
        "text": "暖一点",
    }
    r = c.post("/api/projects/" + p["id"] + "/instructions", json=body)
    assert r.status_code == 503
    r = c.put(
        "/api/projects/" + p["id"] + "/preferences",
        json={"context_revision": p["revision"], "value": "自然暖色"},
    )
    assert r.status_code == 200
    p = c.delete("/api/projects/" + p["id"] + "/messages").json()
    assert p["preferences"]["style_preference"] == "自然暖色"
    assert p["messages"] == [] and len(p["assets"]) == 1
    assert (
        c.delete("/api/projects/" + p["id"] + "/preferences").json()["preferences"]
        == {}
    )


def test_mock_model_scope_memory_and_idempotency(client):
    c = client
    p = create(c)
    model = c.app.state.service.model
    model.plan = AsyncMock(
        return_value=Plan(
            status="ready",
            message="生成预览",
            target_asset_ids=p["selected"],
            adjustments=[Adjustment(field="exposure_ev", op="add", value=0.2)],
        )
    )
    body = {
        "context_revision": p["revision"],
        "request_id": "specific-photo-03",
        "text": "第 3 张再亮一点",
    }
    r = c.post("/api/projects/" + p["id"] + "/instructions", json=body)
    assert r.status_code == 200, r.text
    op = wait(c, r.json()["operation_id"])
    assert [i["ordinal"] for i in op["items"]] == [3]
    assert (
        c.post("/api/projects/" + p["id"] + "/instructions", json=body).json()[
            "operation_id"
        ]
        == op["id"]
    )
    assert model.plan.await_count == 1
    p = c.get("/api/projects/" + p["id"]).json()
    model.plan = AsyncMock(
        return_value=Plan(
            status="ready",
            message="记忆请求",
            memory_actions=[{"op": "set", "value": "喜欢暖色"}],
        )
    )
    r = c.post(
        "/api/projects/" + p["id"] + "/instructions",
        json={
            "context_revision": p["revision"],
            "request_id": "explicit-memory-1",
            "text": "记住，我喜欢暖色",
        },
    )
    assert r.status_code == 200, r.text
    p = c.get("/api/projects/" + p["id"]).json()
    assert p["preferences"]["style_preference"] == "喜欢暖色"
    assert all(a["revision"] == 0 for a in p["assets"])


def test_bad_inputs_limit_and_ranges(client):
    c = client
    p = create(c, 10)
    r = c.post(
        "/api/projects/" + p["id"] + "/assets",
        files={"files": ("extra.png", photo(), "image/png")},
    )
    assert r.json()["files"][0]["status"] == "failed"
    r = c.post(
        "/api/projects/" + p["id"] + "/previews",
        json={
            "context_revision": p["revision"],
            "target_asset_ids": p["selected"],
            "adjustments": [{"field": "warmth", "op": "add", "value": 5}],
        },
    )
    assert r.status_code == 400
    p2 = c.post("/api/projects", json={}).json()
    bad = c.post(
        "/api/projects/" + p2["id"] + "/assets",
        files={"files": ("fake.png", b"not a photo", "image/png")},
    ).json()
    assert bad["files"][0]["status"] == "failed"
    assert bad["project"]["assets"] == []
    assert (
        c.post(
            "/api/projects/" + p2["id"] + "/previews",
            json={"context_revision": 0, "target_asset_ids": p["selected"]},
        ).status_code
        == 400
    )


def test_image_pixels_alpha_orientation_and_icc(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(photo((80, 120, 180, 77), "RGBA"))
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    result = tmp_path / "result.png"
    render(source, result, Recipe().model_dump())
    assert Image.open(result).getpixel((0, 0)) == (80, 120, 180, 77)
    render(
        source, result, Recipe(exposure_ev=0.5, warmth=0.2, saturation=0).model_dump()
    )
    pixel = Image.open(result).getpixel((0, 0))
    assert pixel[0] == pixel[1] == pixel[2] and pixel[3] == 77 and pixel[0] > 100
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    jpeg = tmp_path / "orient.jpg"
    exif = Image.Exif()
    exif[274] = 6
    jpeg.write_bytes(photo(size=(120, 80), format="JPEG", exif=exif))
    render(jpeg, result, Recipe().model_dump())
    assert Image.open(result).size == (80, 120)
    assert inspect(jpeg)["width"] == 80
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    source.write_bytes(photo(icc_profile=profile))
    render(source, result, Recipe().model_dump())
    assert Image.open(result).getpixel((0, 0)) == (80, 120, 180)


def test_restart_restores_and_interrupts(tmp_path):
    settings = Settings(tmp_path, "persistent-secret")
    with TestClient(create_app(settings)) as c:
        p = create(c, 1)
        cookies = dict(c.cookies)
        op = preview(c, p, preset="warm")
        with c.app.state.service.db.connect(write=True) as db:
            db.execute("UPDATE operations SET status='running' WHERE id=?", (op["id"],))
            db.execute(
                "UPDATE operation_items SET status='running' WHERE operation_id=?",
                (op["id"],),
            )
    with TestClient(create_app(settings)) as c:
        c.cookies.update(cookies)
        state = c.get("/api/projects/" + p["id"]).json()
        assert state["assets"][0]["id"] == p["assets"][0]["id"]
        assert state["operations"][0]["status"] == "interrupted"
        assert c.post("/api/operations/" + op["id"] + "/retry").status_code == 200


def test_recipe_rejects_nan_and_cumulative_overflow():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Recipe(warmth=float("nan"))
    with pytest.raises(ValidationError):
        merge_recipe(
            Recipe(warmth=0.95).model_dump(),
            None,
            [Adjustment(field="warmth", op="add", value=0.1)],
        )


def test_delayed_model_result_is_rejected(client):
    c = client
    p = create(c, 1)

    async def delayed(context):
        with c.app.state.service.db.connect(write=True) as db:
            db.execute("UPDATE projects SET revision=revision+1 WHERE id=?", (p["id"],))
        return Plan(
            status="ready",
            message="preview",
            target_asset_ids=p["selected"],
            adjustments=[Adjustment(field="warmth", op="add", value=0.1)],
        )

    c.app.state.service.model.plan = delayed
    r = c.post(
        "/api/projects/" + p["id"] + "/instructions",
        json={
            "context_revision": p["revision"],
            "request_id": "delayed-request-01",
            "text": "暖一点",
        },
    )
    assert r.status_code == 409
    state = c.get("/api/projects/" + p["id"]).json()
    assert state["operations"] == [] and state["assets"][0]["recipe"]["warmth"] == 0


def test_mock_model_unsupported_and_implicit_memory(client):
    c = client
    p = create(c, 1)
    model = c.app.state.service.model
    model.plan = AsyncMock(
        return_value=Plan(status="unsupported", message="暂不支持去路人")
    )
    r = c.post(
        "/api/projects/" + p["id"] + "/instructions",
        json={
            "context_revision": p["revision"],
            "request_id": "unsupported-edit-01",
            "text": "去掉路人",
        },
    )
    assert r.json()["status"] == "unsupported"
    model.plan = AsyncMock(
        return_value=Plan(
            status="ready",
            message="memory",
            memory_actions=[{"op": "set", "value": "暖色"}],
        )
    )
    r = c.post(
        "/api/projects/" + p["id"] + "/instructions",
        json={
            "context_revision": p["revision"],
            "request_id": "implicit-memory-01",
            "text": "暖一点",
        },
    )
    assert r.status_code == 400
    assert c.get("/api/projects/" + p["id"]).json()["preferences"] == {}


def test_queue_capacity_and_viewing_preserve_preview(client):
    c = client
    p = create(c, 2)
    c.app.state.service.pending = 20
    r = c.post(
        "/api/projects/" + p["id"] + "/previews",
        json={
            "context_revision": p["revision"],
            "target_asset_ids": p["selected"],
            "preset_id": "warm",
        },
    )
    assert r.status_code == 429
    c.app.state.service.pending = 0
    assert c.get("/api/projects/" + p["id"]).json()["operations"] == []
    op = preview(c, p, preset="warm")
    p = c.get("/api/projects/" + p["id"]).json()
    r = c.patch(
        "/api/projects/" + p["id"] + "/workspace",
        json={
            "context_revision": p["revision"],
            "selected_asset_ids": p["selected"],
            "viewed_asset_id": p["assets"][1]["id"],
        },
    )
    assert r.status_code == 200
    assert c.post("/api/operations/" + op["id"] + "/apply").status_code == 200
    assert wait(c, op["id"], ("succeeded",))["status"] == "succeeded"


def test_image_limits_animation_and_resize(tmp_path, client):
    c = client
    p = c.post("/api/projects", json={}).json()
    r = c.post(
        "/api/projects/" + p["id"] + "/assets",
        files={"files": ("large.png", b"x" * (10 * 1024 * 1024 + 1), "image/png")},
    )
    assert r.json()["files"][0]["status"] == "failed"
    animated = tmp_path / "animated.png"
    Image.new("RGB", (20, 20), "red").save(
        animated,
        save_all=True,
        append_images=[Image.new("RGB", (20, 20), "blue")],
        duration=100,
    )
    from app.errors import AppError

    with pytest.raises(AppError):
        inspect(animated)
    source = tmp_path / "large.png"
    source.write_bytes(photo(size=(3000, 2000)))
    with pytest.raises(AppError):
        inspect(source, max_pixels=100)
    out = tmp_path / "out.png"
    render(source, out, Recipe().model_dump())
    assert max(Image.open(out).size) == 2560


def test_model_adapter_correction_and_timeout(tmp_path, monkeypatch):
    import httpx
    import app.model as module
    from app.errors import AppError

    settings = Settings(
        tmp_path,
        "secret",
        "https://model.example/chat/completions",
        "example",
        "test-key",
    )
    calls = []
    real = httpx.AsyncClient

    def respond(request):
        calls.append(json.loads(request.content))
        content = (
            "bad-json"
            if len(calls) == 1
            else json.dumps(
                {
                    "status": "ready",
                    "message": "预览",
                    "adjustments": [{"field": "warmth", "op": "add", "value": 0.1}],
                }
            )
        )
        return httpx.Response(
            200, json={"choices": [{"message": {"content": content}}]}
        )

    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(respond), **kw),
    )
    result = asyncio.run(module.ModelClient(settings).plan({"instruction": "暖一点"}))
    assert result.adjustments[0].value == 0.1 and len(calls) == 2

    def timeout(request):
        raise httpx.ReadTimeout("timeout")

    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(timeout), **kw),
    )
    with pytest.raises(AppError, match="超时"):
        asyncio.run(module.ModelClient(settings).plan({}))
