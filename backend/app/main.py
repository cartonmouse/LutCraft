import secrets
import json
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, URLSafeTimedSerializer
from starlette.background import BackgroundTask

from .agent_schemas import BridgeCall, BridgeHello, tool_catalog
from .config import ROOT, Settings
from .db import unpack
from .errors import AppError
from .luts import MAX_BYTES, engine_status
from .schemas import (
    InstructionRequest,
    PreferenceRequest,
    PreviewRequest,
    ProjectRequest,
    RenamePresetRequest,
    ResetRequest,
    SavePresetRequest,
    WorkspaceRequest,
)
from .service import Service
from .library_schemas import MetadataPatch, SearchRequest, SearchIntent, CandidatePreview


def create_app(settings=None):
    settings = settings or Settings.load()

    @asynccontextmanager
    async def lifespan(app):
        app.state.service = Service(settings)
        try:
            yield
        finally:
            await app.state.service.agent.close()
            app.state.service.close()

    app = FastAPI(title="LutCraft", lifespan=lifespan)
    signer = URLSafeTimedSerializer(settings.secret, salt="lut-session")

    @app.middleware("http")
    async def session(request, call_next):
        request.state.request_id = secrets.token_hex(8)
        if request.url.path.startswith("/internal/openclaw/"):
            if request.headers.get("origin"):
                return JSONResponse(
                    {"code": "bridge_origin", "message": "工具接口仅接受服务端请求。"},
                    403,
                )
            try:
                request.app.state.service.agent.authenticate(
                    request.headers.get("authorization")
                )
            except AppError as exc:
                return JSONResponse(
                    {"code": exc.code, "message": exc.message}, exc.status
                )
            # Bound the actual request body, including chunked requests.
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 64 * 1024:
                    return JSONResponse(
                        {"code": "bridge_size", "message": "工具请求过大。"}, 413
                    )
            request._body = bytes(body)
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            return response
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin:
                parsed = urlparse(origin)
                if parsed.netloc != request.headers.get("host") and not (
                    parsed.hostname in ("localhost", "127.0.0.1")
                    and parsed.port in (5173, 8765)
                ):
                    return JSONResponse(
                        {
                            "code": "origin",
                            "message": "请求来源不允许。",
                            "request_id": request.state.request_id,
                        },
                        403,
                    )
            try:
                length = int(request.headers.get("content-length", "0"))
            except ValueError:
                length = 0
            if length > 105 * 1024 * 1024:
                return JSONResponse(
                    {
                        "code": "upload_size",
                        "message": "单次上传总大小不能超过 100 MB。",
                        "request_id": request.state.request_id,
                    },
                    413,
                )
        cookie = request.cookies.get("lut_session", "")
        try:
            owner = signer.loads(cookie, max_age=365 * 24 * 3600)
        except BadSignature:
            owner = secrets.token_urlsafe(32)
            cookie = ""
        request.state.owner = owner
        response = await call_next(request)
        if not cookie:
            response.set_cookie(
                "lut_session",
                signer.dumps(owner),
                httponly=True,
                samesite="strict",
                max_age=365 * 24 * 3600,
            )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(AppError)
    async def app_error(request, exc):
        return JSONResponse(
            {
                "code": exc.code,
                "message": exc.message,
                "request_id": request.state.request_id,
            },
            exc.status,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(
            {
                "code": "invalid_input",
                "message": "请求参数无效，请检查范围或刷新后重试。",
                "request_id": request.state.request_id,
            },
            422,
        )

    def svc(request):
        return request.app.state.service

    def own(request):
        return request.state.owner

    @app.get("/api/health")
    def health(request: Request):
        import pyvips

        return {
            "status": "ok",
            "image_engine": ".".join(str(pyvips.version(i)) for i in range(3)),
            "model_configured": settings.model_configured,
            "model_name": settings.model_name if settings.model_configured else None,
            "lut_engine": engine_status(),
            "agent": svc(request).agent.health(),
            "embedding": {"configured": svc(request).embeddings.configured,
                          "model": settings.embedding_model or None,
                          "calibrated": settings.embedding_min_similarity is not None},
        }

    @app.post("/api/projects")
    def create_project(body: ProjectRequest, request: Request):
        return svc(request).create_project(own(request), body.name)

    @app.get("/api/projects")
    def list_projects(request: Request):
        with svc(request).db.connect() as db:
            return [
                dict(p)
                for p in db.execute(
                    "SELECT id,name,created_at FROM projects WHERE owner=? ORDER BY created_at DESC",
                    (own(request),),
                )
            ]

    @app.get("/api/projects/{pid}")
    def get_project(pid: str, request: Request):
        return svc(request).snapshot(pid, own(request))

    @app.patch("/api/projects/{pid}/workspace")
    def workspace(pid: str, body: WorkspaceRequest, request: Request):
        return svc(request).workspace(pid, own(request), body)

    @app.post("/api/projects/{pid}/assets")
    def upload(pid: str, request: Request, files: list[UploadFile] = File(...)):
        try:
            if len(files) > 10:
                raise AppError("asset_limit", "每次最多上传 10 张照片。")
            payload = [
                (f.filename or "photo", f.file.read(settings.max_bytes + 1))
                for f in files
            ]
            return svc(request).upload(pid, own(request), payload)
        finally:
            for f in files:
                f.file.close()

    @app.post("/api/projects/{pid}/previews")
    def preview(pid: str, body: PreviewRequest, request: Request):
        return svc(request).preview(pid, own(request), body)

    @app.post("/api/projects/{pid}/reset-preview")
    def reset_preview(pid: str, body: ResetRequest, request: Request):
        return svc(request).reset_preview(pid, own(request), body)

    @app.get("/api/luts")
    def list_luts(request: Request):
        return svc(request).luts.list(own(request))

    @app.post("/api/luts")
    def upload_lut(
        request: Request,
        file: UploadFile = File(...),
        name: str = Form(""),
        color_space: str = Form(...),
        metadata: str = Form(""),
    ):
        try:
            if color_space not in ("srgb", "unknown"):
                raise AppError(
                    "lut_space", "本轮只支持输入与输出均为 sRGB 照片的 LUT。"
                )
            try:
                if len(metadata) > 24000:
                    raise ValueError()
                raw = json.loads(metadata) if metadata else None
            except ValueError as exc:
                raise AppError("metadata_format", "元信息不是有效的 JSON 或内容过长。") from exc
            return svc(request).luts.upload(own(request), file.filename or "", file.file.read(MAX_BYTES + 1), name, color_space, raw)
        finally:
            file.file.close()

    @app.get("/api/luts/{lid}/metadata")
    def lut_metadata(lid: str, request: Request):
        return svc(request).metadata.get(own(request), lid)

    @app.patch("/api/luts/{lid}/metadata")
    def update_lut_metadata(lid: str, body: MetadataPatch, request: Request):
        return svc(request).metadata.patch(own(request), lid, body)

    @app.post("/api/luts/{lid}/analyze")
    def analyze_lut(lid: str, request: Request):
        return svc(request).metadata.enqueue(own(request), lid)

    @app.get("/api/lut-jobs/{jid}")
    def lut_job(jid: str, request: Request):
        return svc(request).metadata.job(own(request), jid)

    @app.post("/api/luts/search")
    def search_luts(body: SearchRequest, request: Request):
        return svc(request).search.search(own(request), SearchIntent(**body.model_dump(exclude={"project_id"})), body.project_id)

    @app.post("/api/projects/{pid}/candidate-preview")
    def preview_candidate(pid: str, body: CandidatePreview, request: Request):
        s = svc(request)
        with s.lock:
            s.search.validate(own(request), pid, body.search_id, body.lut_id)
            return s.preview(pid, own(request), PreviewRequest(context_revision=body.context_revision,
                target_asset_ids=body.target_asset_ids,
                search_id=body.search_id,
                lut_action={"op": "select", "id": body.lut_id, "strength": body.strength}))

    @app.get("/api/personal-presets")
    def list_presets(request: Request):
        return svc(request).presets.list(own(request))

    @app.post("/api/personal-presets")
    def save_preset(body: SavePresetRequest, request: Request):
        return svc(request).presets.save(own(request), body)

    @app.patch("/api/personal-presets/{preset_id}")
    def rename_preset(preset_id: str, body: RenamePresetRequest, request: Request):
        return svc(request).presets.rename(own(request), preset_id, body)

    @app.delete("/api/personal-presets/{preset_id}")
    def delete_preset(preset_id: str, request: Request):
        return svc(request).presets.delete(own(request), preset_id)

    @app.post("/api/projects/{pid}/instructions")
    async def instruction(pid: str, body: InstructionRequest, request: Request):
        s = svc(request)
        if settings.agent_runtime == "direct":
            return await s.instruction(pid, own(request), body)
        if settings.agent_runtime == "manual":
            raise AppError(
                "agent_not_ready", "OpenClaw 待接入，当前可使用参数调色。", 503
            )
        result = s.agent.start(pid, own(request), body)
        return JSONResponse(result, status_code=202)

    @app.get("/api/agent-turns/{tid}")
    def agent_turn(tid: str, request: Request):
        return svc(request).agent.get(tid, own(request))

    @app.post("/api/agent-turns/{tid}/cancel")
    async def cancel_agent_turn(tid: str, request: Request):
        return svc(request).agent.cancel(tid, own(request))

    @app.post("/internal/openclaw/hello")
    def bridge_hello(body: BridgeHello, request: Request):
        return svc(request).agent.hello(body)

    @app.get("/internal/openclaw/catalog")
    def bridge_catalog():
        return {"contract_version": 1, "tools": tool_catalog()}

    @app.post("/internal/openclaw/invoke")
    def bridge_call(body: BridgeCall, request: Request):
        return svc(request).agent.invoke(body)

    @app.get("/api/operations/{oid}")
    def get_operation(oid: str, request: Request):
        s = svc(request)
        with s.db.connect() as db:
            return s.op_public(db, s.operation(db, oid, own(request)))

    @app.post("/api/operations/{oid}/apply")
    def apply(oid: str, request: Request):
        return svc(request).apply(oid, own(request))

    @app.post("/api/operations/{oid}/retry")
    def retry(oid: str, request: Request):
        return svc(request).retry(oid, own(request))

    @app.post("/api/operations/{oid}/discard")
    def discard(oid: str, request: Request):
        s = svc(request)
        with s.lock, s.db.connect(write=True) as db:
            op = s.operation(db, oid, own(request))
            if op["status"] not in ("previewing", "ready"):
                raise AppError("discard_state", "只能放弃尚未应用的预览。", 409)
            db.execute("UPDATE operations SET status='discarded' WHERE id=?", (oid,))
            db.execute(
                "UPDATE projects SET revision=revision+1 WHERE id=?",
                (op["project_id"],),
            )
        return {"status": "discarded"}

    @app.get("/api/projects/{pid}/memory")
    def memory(pid: str, request: Request):
        p = svc(request).snapshot(pid, own(request))
        return {k: p[k] for k in ("preferences", "assets", "operations")}

    @app.delete("/api/projects/{pid}/messages")
    def clear_messages(pid: str, request: Request):
        return svc(request).clear(pid, own(request), "messages")

    @app.delete("/api/projects/{pid}/preferences")
    def clear_preferences(pid: str, request: Request):
        return svc(request).clear(pid, own(request), "preferences")

    @app.put("/api/projects/{pid}/preferences")
    def save_preferences(pid: str, body: PreferenceRequest, request: Request):
        from .db import dump

        s = svc(request)
        with s.lock, s.db.connect(write=True) as db:
            p = s.project(db, pid, own(request))
            s.writable(db, pid)
            s.revision(p, body.context_revision)
            s.agent.invalidate(db, pid)
            preferences = (
                {"style_preference": body.value.strip()} if body.value.strip() else {}
            )
            db.execute(
                "UPDATE projects SET preferences_json=?,revision=revision+1 WHERE id=?",
                (dump(preferences), pid),
            )
            db.execute(
                "UPDATE operations SET source_revision=source_revision+1 WHERE project_id=? AND status IN ('ready','previewing')",
                (pid,),
            )
        return s.snapshot(pid, own(request))

    @app.get("/api/assets/{aid}/files/{kind}")
    def asset_file(aid: str, kind: str, request: Request, download: bool = False):
        s = svc(request)
        with s.db.connect() as db:
            a = unpack(db.execute("SELECT * FROM assets WHERE id=?", (aid,)).fetchone())
            if not a:
                raise AppError("not_found", "照片不存在。", 404)
            s.project(db, a["project_id"], own(request))
            key = {
                "original": "original",
                "thumbnail": "thumbnail",
                "base": "base_preview",
                "current": "result",
            }.get(kind)
            if not key or not a[key]:
                raise AppError("not_found", "该图片结果尚未生成。", 404)
            p = s.path(a[key])
        if not p.is_file():
            raise AppError("missing_file", "图片文件不存在，请重新处理。", 404)
        return FileResponse(
            p, filename=f"{a['ordinal']:02d}-edited.{a['format']}" if download else None
        )

    @app.get("/api/operations/{oid}/files/{file_id}")
    def operation_file(
        oid: str, file_id: str, request: Request, download: bool = False
    ):
        s = svc(request)
        with s.db.connect() as db:
            op = s.operation(db, oid, own(request))
            if file_id == "preview":
                ref = op["preview"]
            else:
                item = db.execute(
                    "SELECT result FROM operation_items WHERE operation_id=? AND asset_id=? AND status='succeeded'",
                    (oid, file_id),
                ).fetchone()
                ref = item[0] if item else None
            if not ref:
                raise AppError("not_found", "该操作结果尚未生成。", 404)
            p = s.path(ref)
        if not p.is_file():
            raise AppError("missing_file", "图片文件不存在。", 404)
        return FileResponse(p, filename=p.name if download else None)

    @app.get("/api/operations/{oid}/download.zip")
    def download_zip(oid: str, request: Request):
        p = svc(request).zip(oid, own(request))
        return FileResponse(
            p,
            filename=f"lut-{oid[:8]}.zip",
            background=BackgroundTask(p.unlink, missing_ok=True),
        )

    dist = ROOT / "frontend/dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()
