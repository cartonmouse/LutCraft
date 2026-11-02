import json
import logging
import re
import shutil
import threading
import zipfile
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from pydantic import ValidationError
from .db import Database, uid, now, dump, unpack
from .errors import AppError
from .schemas import Recipe, PreviewRequest, Plan
from .recipes import merge_recipe
from . import imaging
from .model import ModelClient
from .luts import LutLibrary
from .preset_library import PresetLibrary
from .operation_receipts import plan_summary, status_message

log = logging.getLogger(__name__)
ACTIVE = ("queued", "running")
TERMINAL = ("succeeded", "partial_failed", "failed", "interrupted")


class Service:
    def __init__(self, settings):
        self.settings = settings
        settings.data.mkdir(parents=True, exist_ok=True)
        self.db = Database(settings.data / "lut.sqlite3")
        self.model = ModelClient(settings)
        self.luts = LutLibrary(self.db, self.path)
        self.presets = PresetLibrary(self)
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lut-images")
        self.pending = 0
        from .embeddings import Embeddings
        from .lut_metadata import LutMetadata
        from .lut_search import LutSearch
        self.embeddings = Embeddings(settings)
        self.metadata = LutMetadata(self, self.embeddings)
        self.luts.metadata = self.metadata
        self.search = LutSearch(self, self.embeddings)
        from .agent_service import AgentService
        self.agent = AgentService(self)

    def close(self):
        self.metadata.close()
        self.pool.shutdown(wait=True)

    def path(self, ref):
        p = (self.settings.data / ref).resolve()
        if not p.is_relative_to(self.settings.data.resolve()):
            raise AppError("file_path", "无效文件引用。", 400)
        return p

    def project(self, db, pid, owner):
        p = unpack(
            db.execute(
                "SELECT * FROM projects WHERE id=? AND owner=?", (pid, owner)
            ).fetchone()
        )
        if not p:
            raise AppError("not_found", "项目不存在或不属于当前浏览器会话。", 404)
        return p

    def operation(self, db, oid, owner):
        op = unpack(
            db.execute("SELECT * FROM operations WHERE id=?", (oid,)).fetchone()
        )
        if not op:
            raise AppError("not_found", "操作不存在。", 404)
        self.project(db, op["project_id"], owner)
        return op

    def writable(self, db, pid):
        if db.execute(
            "SELECT 1 FROM operations WHERE project_id=? AND status IN ('queued','running')",
            (pid,),
        ).fetchone():
            raise AppError("project_busy", "当前影集正在处理，请完成后再调整。", 409)

    def revision(self, p, expected):
        if p["revision"] != expected:
            raise AppError("stale_state", "项目状态已变化，请刷新后重新生成预览。", 409)

    def create_project(self, owner, name):
        pid = uid()
        with self.db.connect(write=True) as db:
            db.execute(
                "INSERT INTO projects(id,owner,name,created_at) VALUES (?,?,?,?)",
                (pid, owner, name, now()),
            )
        return self.snapshot(pid, owner)

    def asset_public(self, a):
        result = {
            k: v
            for k, v in a.items()
            if k not in ("original", "thumbnail", "base_preview", "result")
        }
        base = f"/api/assets/{a['id']}/files"
        result["recipe"] = Recipe.model_validate(a["recipe"]).model_dump()
        result.update(
            thumbnail_url=base + "/thumbnail",
            original_url=base + "/base",
            result_url=(base + f"/current?v={a['revision']}") if a["result"] else None,
            download_url=base + "/current?download=1" if a["result"] else None,
        )
        return result

    def op_public(self, db, op):
        op = dict(op)
        op["items"] = []
        for r in db.execute(
            "SELECT i.*,a.ordinal,a.name FROM operation_items i JOIN assets a ON a.id=i.asset_id WHERE operation_id=? ORDER BY a.ordinal",
            (op["id"],),
        ):
            item = unpack(r)
            item["recipe"] = Recipe.model_validate(item["recipe"]).model_dump()
            ref = item.pop("result")
            item["result_url"] = (
                f"/api/operations/{op['id']}/files/{item['asset_id']}" if ref else None
            )
            op["items"].append(item)
        ref = op.pop("preview")
        op["preview_url"] = f"/api/operations/{op['id']}/files/preview" if ref else None
        op["download_url"] = (
            f"/api/operations/{op['id']}/download.zip"
            if op["status"] in TERMINAL
            and any(i["status"] == "succeeded" for i in op["items"])
            else None
        )
        return op

    def snapshot(self, pid, owner):
        with self.db.connect() as db:
            p = self.project(db, pid, owner)
            p.pop("owner")
            p["assets"] = [
                self.asset_public(unpack(a))
                for a in db.execute(
                    "SELECT * FROM assets WHERE project_id=? ORDER BY ordinal", (pid,)
                )
            ]
            p["messages"] = [
                unpack(m)
                for m in db.execute(
                    "SELECT id,role,content,operation_id,request_id,created_at FROM messages WHERE project_id=? ORDER BY created_at",
                    (pid,),
                )
            ]
            ops = [
                unpack(o)
                for o in db.execute(
                    "SELECT * FROM operations WHERE project_id=? ORDER BY created_at DESC LIMIT 30",
                    (pid,),
                )
            ]
            p["operations"] = [self.op_public(db, o) for o in ops]
            operations = {op["id"]: op for op in p["operations"]}
            for message in p["messages"]:
                rid = message.pop("request_id")
                if message["role"] != "assistant" or not rid or not message["operation_id"]:
                    continue
                oid = message["operation_id"]
                op = operations.get(oid)
                if not op:
                    row = unpack(db.execute("SELECT * FROM operations WHERE id=? AND project_id=?", (oid, pid)).fetchone())
                    if not row:
                        continue
                    op = self.op_public(db, row)
                    operations[oid] = op
                explanation = op["summary"]
                if not (explanation.startswith("方案：") and "\n处理范围：" in explanation):
                    # Old chats also get live status and factual recipes. Recover only
                    # the search receipt belonging to this exact request, if available.
                    row = db.execute("SELECT response_json FROM messages WHERE project_id=? AND request_id=? AND role='user'", (pid, rid)).fetchone()
                    result = json.loads(row[0]) if row and row[0] else {}
                    explanation = plan_summary(op["items"], op["preview_asset_id"], search=result.get("lut_search"))
                prefix = "项目偏好已更新。" if message["content"].startswith("项目偏好已更新。") else ""
                message["content"] = prefix + status_message(op)
                message["operation"] = {"id": oid, "status": op["status"], "summary": explanation}
            p["agent_turns"] = [self.agent.public(dict(t)) for t in db.execute(
                "SELECT * FROM agent_turns WHERE project_id=? ORDER BY created_at DESC LIMIT 10", (pid,))]
            p["lut_search"] = self.search.latest(owner, pid, db)
            return p

    def workspace(self, pid, owner, req):
        with self.lock, self.db.connect(write=True) as db:
            p = self.project(db, pid, owner)
            self.revision(p, req.context_revision)
            ids = {
                r[0]
                for r in db.execute("SELECT id FROM assets WHERE project_id=?", (pid,))
            }
            selected = list(dict.fromkeys(req.selected_asset_ids))
            if not set(selected) <= ids or (
                req.viewed_asset_id and req.viewed_asset_id not in ids
            ):
                raise AppError("asset_scope", "所选照片不属于当前项目。")
            changed = set(p["selected"]) != set(selected)
            if changed:
                self.writable(db, pid)
                db.execute(
                    "UPDATE operations SET status='stale' WHERE project_id=? AND status IN ('previewing','ready')",
                    (pid,),
                )
            # Viewing changes affect the meaning of “this one”, but not a ready preview's explicit scope.
            bump = changed or p["viewed"] != req.viewed_asset_id
            db.execute(
                "UPDATE projects SET selected_json=?, viewed=?, revision=revision+? WHERE id=?",
                (dump(selected), req.viewed_asset_id, int(bump), pid),
            )
            if bump and not changed:
                db.execute(
                    "UPDATE operations SET source_revision=source_revision+1 WHERE project_id=? AND status IN ('previewing','ready')",
                    (pid,),
                )
        return self.snapshot(pid, owner)

    def upload(self, pid, owner, files):
        results = []
        with self.lock:
            with self.db.connect() as db:
                self.project(db, pid, owner)
                self.writable(db, pid)
            for filename, data in files:
                directory = None
                try:
                    with self.db.connect() as db:
                        count = db.execute(
                            "SELECT COUNT(*) FROM assets WHERE project_id=?", (pid,)
                        ).fetchone()[0]
                    if count >= self.settings.max_assets:
                        raise AppError("asset_limit", "每个影集最多 10 张照片。")
                    if len(data) > self.settings.max_bytes:
                        raise AppError("file_size", "单张照片不能超过 10 MB。")
                    aid = uid()
                    directory = self.path(f"{pid}/assets/{aid}")
                    directory.mkdir(parents=True)
                    original = directory / "original.bin"
                    original.write_bytes(data)
                    meta = imaging.inspect(original, self.settings.max_pixels)
                    original = original.rename(directory / f"original.{meta['format']}")
                    thumb = directory / "thumbnail.png"
                    base = directory / f"base.{meta['format']}"
                    imaging.render(original, thumb, Recipe().model_dump(), 320)
                    imaging.render(original, base, Recipe().model_dump(), 1280)
                    ref = lambda p: str(p.relative_to(self.settings.data))
                    with self.db.connect(write=True) as db:
                        p = self.project(db, pid, owner)
                        ordinal = db.execute(
                            "SELECT COALESCE(MAX(ordinal),0)+1 FROM assets WHERE project_id=?",
                            (pid,),
                        ).fetchone()[0]
                        db.execute(
                            "INSERT INTO assets(id,project_id,ordinal,name,original,thumbnail,base_preview,width,height,format,recipe_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                aid,
                                pid,
                                ordinal,
                                Path(filename).name[:200],
                                ref(original),
                                ref(thumb),
                                ref(base),
                                meta["width"],
                                meta["height"],
                                meta["format"],
                                dump(Recipe().model_dump()),
                            ),
                        )
                        db.execute(
                            "UPDATE projects SET selected_json=?,viewed=COALESCE(viewed,?),revision=revision+1 WHERE id=?",
                            (dump(p["selected"] + [aid]), aid, pid),
                        )
                        db.execute(
                            "UPDATE operations SET status='stale' WHERE project_id=? AND status IN ('previewing','ready')",
                            (pid,),
                        )
                    results.append(
                        {"name": filename, "asset_id": aid, "status": "succeeded"}
                    )
                except Exception as exc:
                    if not isinstance(exc, AppError):
                        log.exception("Upload processing failed")
                    if directory:
                        shutil.rmtree(directory, ignore_errors=True)
                    message = (
                        exc.message
                        if isinstance(exc, AppError)
                        else "图片无法解码或颜色配置不受支持，请换一张 JPEG/PNG。"
                    )
                    results.append(
                        {"name": filename, "status": "failed", "error": message}
                    )
        return {"files": results, "project": self.snapshot(pid, owner)}

    def reserve(self, n):
        if self.pending + n > self.settings.queue_limit:
            raise AppError("queue_full", "处理队列已满，请稍后重试。", 429)
        self.pending += n

    def submit(self, fn, n, *args):
        def work():
            try:
                fn(*args)
            except Exception:
                log.exception("Background operation failed: %s", args[0])
                with self.db.connect(write=True) as db:
                    oid = args[0]
                    successes = db.execute(
                        "SELECT COUNT(*) FROM operation_items WHERE operation_id=? AND status='succeeded'",
                        (oid,),
                    ).fetchone()[0]
                    db.execute(
                        "UPDATE operation_items SET status='failed',error='后台任务中断，可重试' WHERE operation_id=? AND status IN ('queued','running','planned')",
                        (oid,),
                    )
                    db.execute(
                        "UPDATE operations SET status=?,error='后台任务中断，可重试' WHERE id=?",
                        ("partial_failed" if successes else "failed", oid),
                    )
            finally:
                with self.lock:
                    self.pending -= n

        self.pool.submit(work)

    def preview(
        self, pid, owner, req, summary="已生成调色方案，请检查预览。", recipes=None, commit_hook=None
    ):
        with self.lock:
            with self.db.connect(write=True) as db:
                p = self.project(db, pid, owner)
                self.writable(db, pid)
                self.revision(p, req.context_revision)
                search_receipt = None
                if req.search_id:
                    if not req.lut_action or req.lut_action.op != "select":
                        raise AppError("candidate_invalid", "候选预览必须指定 LUT。")
                    self.search.validate(owner, pid, req.search_id, req.lut_action.id, db)
                    search_receipt = json.loads(db.execute("SELECT result_json FROM lut_search_runs WHERE id=?", (req.search_id,)).fetchone()[0])
                targets = set(req.target_asset_ids)
                assets = [
                    unpack(a)
                    for a in db.execute(
                        "SELECT * FROM assets WHERE project_id=? ORDER BY ordinal",
                        (pid,),
                    )
                    if a["id"] in targets
                ]
                if len(assets) != len(targets) or not assets:
                    raise AppError("asset_scope", "请先选择当前项目中的照片。")
                # Keep the image the user is examining as the batch's sample.
                # A viewed image outside the explicit selection is never included.
                preview_asset_id = p["viewed"] if p["viewed"] in targets else assets[0]["id"]
                old = unpack(
                    db.execute(
                        "SELECT * FROM operations WHERE project_id=? AND status='ready' ORDER BY created_at DESC LIMIT 1",
                        (pid,),
                    ).fetchone()
                )
                base = {}
                if (
                    old
                    and targets <= set(old["targets"])
                    and old["source_revision"] == p["revision"]
                ):
                    base = {
                        r["asset_id"]: json.loads(r["recipe_json"])
                        for r in db.execute(
                            "SELECT * FROM operation_items WHERE operation_id=?",
                            (old["id"],),
                        )
                    }
                try:
                    personal = self.presets.get(db, req.personal_preset_id, owner) if req.personal_preset_id else None
                    candidates = {
                        a["id"]: Recipe.model_validate(recipes[a["id"]]).model_dump()
                        if recipes
                        else merge_recipe(
                            personal["recipe"] if personal else base.get(a["id"], a["recipe"]),
                            req.preset_id,
                            req.adjustments,
                        )
                        for a in assets
                    }
                    candidates = {
                        aid: self.luts.update_recipe(db, recipe, req.lut_action, owner)
                        for aid, recipe in candidates.items()
                    }
                except ValidationError as exc:
                    raise AppError(
                        "recipe_range", "调整后的参数超出允许范围，请减小幅度。"
                    ) from exc
                summary = plan_summary(
                    [{"asset_id": a["id"], "ordinal": a["ordinal"], "recipe": candidates[a["id"]]} for a in assets],
                    preview_asset_id, before={a["id"]: base.get(a["id"], a["recipe"]) for a in assets},
                    search=search_receipt, request=req, personal_name=personal["name"] if personal else None,
                )
                if self.pending + 1 > self.settings.queue_limit:
                    raise AppError("queue_full", "处理队列已满，请稍后重试。", 429)
                oid = uid()
                revision = p["revision"] + 1
                db.execute(
                    "UPDATE operations SET status='superseded' WHERE project_id=? AND status IN ('ready','previewing')",
                    (pid,),
                )
                db.execute("UPDATE projects SET revision=? WHERE id=?", (revision, pid))
                db.execute(
                    "INSERT INTO operations(id,project_id,status,source_revision,targets_json,summary,preview_asset_id,created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        oid,
                        pid,
                        "previewing",
                        revision,
                        dump([a["id"] for a in assets]),
                        summary,
                        preview_asset_id,
                        now(),
                    ),
                )
                for a in assets:
                    db.execute(
                        "INSERT INTO operation_items(operation_id,asset_id,source_revision,recipe_json,status) VALUES (?,?,?,?,?)",
                        (
                            oid,
                            a["id"],
                            a["revision"],
                            dump(candidates[a["id"]]),
                            "planned",
                        ),
                    )
                result = {"status": "previewing", "operation_id": oid,
                          "message": "正在生成真实图片预览。"}
                if commit_hook:
                    commit_hook(db, result)
            self.reserve(1)
            self.submit(self.render_preview, 1, oid)
        return result

    def reset_preview(self, pid, owner, req):
        return self.preview(pid, owner, PreviewRequest(**req.model_dump()),
                            "恢复原图效果：清除所选照片的基础调色与 LUT，项目记忆保留。",
                            {aid: Recipe().model_dump() for aid in req.target_asset_ids})

    def render_recipe(self, source, target, recipe, owner, max_edge=2560):
        recipe = Recipe.model_validate(recipe).model_dump()
        if recipe["lut"]:
            with self.db.connect() as db:
                processor = self.luts.resolve(db, recipe["lut"], owner)
            return imaging.render(source, target, recipe, max_edge, processor)
        return imaging.render(source, target, recipe, max_edge)

    def render_preview(self, oid):
        try:
            with self.db.connect() as db:
                op = unpack(
                    db.execute("SELECT * FROM operations WHERE id=?", (oid,)).fetchone()
                )
                if op["status"] != "previewing":
                    return
                a = unpack(
                    db.execute(
                        "SELECT * FROM assets WHERE id=?", (op["preview_asset_id"],)
                    ).fetchone()
                )
                item = unpack(
                    db.execute(
                        "SELECT * FROM operation_items WHERE operation_id=? AND asset_id=?",
                        (oid, a["id"]),
                    ).fetchone()
                )
                owner = db.execute("SELECT owner FROM projects WHERE id=?", (op["project_id"],)).fetchone()[0]
            ref = f"{op['project_id']}/operations/{oid}/preview.{a['format']}"
            self.render_recipe(
                self.path(a["original"]), self.path(ref), item["recipe"], owner, 1280
            )
            with self.lock, self.db.connect(write=True) as db:
                current = unpack(
                    db.execute("SELECT * FROM operations WHERE id=?", (oid,)).fetchone()
                )
                p = unpack(
                    db.execute(
                        "SELECT * FROM projects WHERE id=?", (op["project_id"],)
                    ).fetchone()
                )
                if current["status"] == "previewing":
                    state = (
                        "ready"
                        if p["revision"] == current["source_revision"]
                        else "stale"
                    )
                    db.execute(
                        "UPDATE operations SET status=?,preview=? WHERE id=?",
                        (state, ref, oid),
                    )
        except Exception as exc:
            log.exception("Preview failed: %s", oid)
            with self.db.connect(write=True) as db:
                db.execute(
                    "UPDATE operations SET status='failed',error=? WHERE id=? AND status='previewing'",
                    (
                        exc.message
                        if isinstance(exc, AppError)
                        else "预览处理失败，请重试。",
                        oid,
                    ),
                )

    def apply(self, oid, owner):
        with self.lock:
            with self.db.connect(write=True) as db:
                op = self.operation(db, oid, owner)
                if op["status"] in ACTIVE + ("succeeded", "partial_failed"):
                    return self.op_public(db, op)
                if op["status"] != "ready":
                    raise AppError("not_ready", "该预览不可应用，请重新生成。", 409)
                p = self.project(db, op["project_id"], owner)
                self.writable(db, p["id"])
                self.revision(p, op["source_revision"])
                items = [
                    unpack(r)
                    for r in db.execute(
                        "SELECT * FROM operation_items WHERE operation_id=?", (oid,)
                    )
                ]
                for item in items:
                    self.luts.update_recipe(db, item["recipe"], None, owner)
                    rev = db.execute(
                        "SELECT revision FROM assets WHERE id=?", (item["asset_id"],)
                    ).fetchone()[0]
                    if rev != item["source_revision"]:
                        raise AppError(
                            "stale_state", "照片已变化，请重新生成预览。", 409
                        )
                if self.pending + len(items) > self.settings.queue_limit:
                    raise AppError("queue_full", "队列繁忙，请稍后应用。", 429)
                db.execute("UPDATE operations SET status='queued' WHERE id=?", (oid,))
                db.execute(
                    "UPDATE operation_items SET status='queued' WHERE operation_id=?",
                    (oid,),
                )
            self.reserve(len(items))
            self.submit(self.render_batch, len(items), oid)
        return {"id": oid, "status": "queued"}

    def render_batch(self, oid):
        with self.db.connect(write=True) as db:
            op = unpack(
                db.execute("SELECT * FROM operations WHERE id=?", (oid,)).fetchone()
            )
            db.execute("UPDATE operations SET status='running' WHERE id=?", (oid,))
            items = [
                unpack(i)
                for i in db.execute(
                    "SELECT * FROM operation_items WHERE operation_id=?", (oid,)
                )
            ]
            owner = db.execute("SELECT owner FROM projects WHERE id=?", (op["project_id"],)).fetchone()[0]
        for item in items:
            aid = item["asset_id"]
            try:
                with self.db.connect(write=True) as db:
                    a = unpack(
                        db.execute("SELECT * FROM assets WHERE id=?", (aid,)).fetchone()
                    )
                    db.execute(
                        "UPDATE operation_items SET status='running' WHERE operation_id=? AND asset_id=?",
                        (oid, aid),
                    )
                ref = f"{op['project_id']}/operations/{oid}/{aid}.{a['format']}"
                item["recipe"] = Recipe.model_validate(item["recipe"]).model_dump()
                self.render_recipe(self.path(a["original"]), self.path(ref), item["recipe"], owner)
                with self.lock, self.db.connect(write=True) as db:
                    changed = db.execute(
                        "UPDATE assets SET result=?,recipe_json=?,revision=revision+1 WHERE id=? AND revision=?",
                        (ref, dump(item["recipe"]), aid, item["source_revision"]),
                    ).rowcount
                    if not changed:
                        raise AppError(
                            "stale_asset", "照片配方已变化，本次结果未应用。", 409
                        )
                    db.execute(
                        "UPDATE operation_items SET status='succeeded',result=? WHERE operation_id=? AND asset_id=?",
                        (ref, oid, aid),
                    )
            except Exception as exc:
                log.exception("Render failed: %s/%s", oid, aid)
                with self.db.connect(write=True) as db:
                    db.execute(
                        "UPDATE operation_items SET status='failed',error=? WHERE operation_id=? AND asset_id=?",
                        (
                            exc.message
                            if isinstance(exc, AppError)
                            else "图片处理失败，可重试。",
                            oid,
                            aid,
                        ),
                    )
        with self.lock, self.db.connect(write=True) as db:
            succeeded = db.execute(
                "SELECT COUNT(*) FROM operation_items WHERE operation_id=? AND status='succeeded'",
                (oid,),
            ).fetchone()[0]
            state = (
                "succeeded"
                if succeeded == len(items)
                else "partial_failed"
                if succeeded
                else "failed"
            )
            db.execute("UPDATE operations SET status=? WHERE id=?", (state, oid))
            db.execute(
                "UPDATE projects SET revision=revision+1 WHERE id=?",
                (op["project_id"],),
            )
            db.execute(
                "INSERT INTO messages(id,project_id,role,content,operation_id,created_at) VALUES (?,?,?,?,?,?)",
                (
                    uid(),
                    op["project_id"],
                    "assistant",
                    f"本次处理完成：{succeeded} 张成功，{len(items) - succeeded} 张失败。",
                    oid,
                    now(),
                ),
            )

    def retry(self, oid, owner):
        with self.lock, self.db.connect() as db:
            op = self.operation(db, oid, owner)
            if op["status"] not in ("failed", "partial_failed", "interrupted"):
                raise AppError("retry_state", "该操作没有可重试的失败项。", 409)
            p = self.project(db, op["project_id"], owner)
            items = [
                unpack(r)
                for r in db.execute(
                    "SELECT * FROM operation_items WHERE operation_id=? AND status!='succeeded'",
                    (oid,),
                )
            ]
            for item in items:
                a = db.execute(
                    "SELECT revision FROM assets WHERE id=?", (item["asset_id"],)
                ).fetchone()
                if a[0] != item["source_revision"]:
                    raise AppError(
                        "stale_state", "失败项的配方已变化，请重新下达调色指令。", 409
                    )
            if not items:
                raise AppError("retry_empty", "没有可重试的照片。")
            req = PreviewRequest(
                context_revision=p["revision"],
                target_asset_ids=[i["asset_id"] for i in items],
            )
        return self.preview(
            p["id"],
            owner,
            req,
            "重新预览失败项，确认后再次处理。",
            {i["asset_id"]: i["recipe"] for i in items},
        )

    def clear(self, pid, owner, kind):
        with self.lock, self.db.connect(write=True) as db:
            self.project(db, pid, owner)
            self.writable(db, pid)
            self.agent.invalidate(db, pid)
            if kind == "messages":
                db.execute("DELETE FROM messages WHERE project_id=?", (pid,))
            else:
                db.execute(
                    "UPDATE projects SET preferences_json='{}' WHERE id=?", (pid,)
                )
            db.execute("UPDATE projects SET revision=revision+1 WHERE id=?", (pid,))
            db.execute(
                "UPDATE operations SET status='stale' WHERE project_id=? AND status IN ('ready','previewing')",
                (pid,),
            )
        return self.snapshot(pid, owner)

    async def instruction(self, pid, owner, req):
        memory_saved = False
        with self.lock, self.db.connect(write=True) as db:
            p = self.project(db, pid, owner)
            previous = db.execute(
                "SELECT response_json FROM messages WHERE project_id=? AND request_id=? AND role='user'",
                (pid, req.request_id),
            ).fetchone()
            if previous:
                return (
                    json.loads(previous[0])
                    if previous[0]
                    else {"status": "pending", "message": "这条指令正在处理。"}
                )
            self.writable(db, pid)
            self.revision(p, req.context_revision)
            assets = [
                unpack(a)
                for a in db.execute(
                    "SELECT * FROM assets WHERE project_id=? ORDER BY ordinal", (pid,)
                )
            ]
            recent = [
                dict(m)
                for m in db.execute(
                    "SELECT role,content FROM messages WHERE project_id=? ORDER BY created_at DESC LIMIT 10",
                    (pid,),
                )
            ][::-1]
            old = unpack(
                db.execute(
                    "SELECT * FROM operations WHERE project_id=? AND status='ready' ORDER BY created_at DESC LIMIT 1",
                    (pid,),
                ).fetchone()
            )
            pending = self.op_public(db, old) if old else None
            context = {
                "instruction": req.text,
                "selected_asset_ids": p["selected"],
                "viewed_asset_id": p["viewed"],
                "assets": [
                    {k: a[k] for k in ("id", "ordinal", "recipe", "revision")}
                    for a in assets
                ],
                "preferences": p["preferences"],
                "pending_preview": pending,
                "recent_messages": recent,
                "lut_candidates": self.search.latest(owner, pid, db),
                "search_complete": False,
            }
            db.execute(
                "INSERT INTO messages(id,project_id,request_id,role,content,created_at) VALUES (?,?,?,?,?,?)",
                (uid(), pid, req.request_id, "user", req.text, now()),
            )
        try:
            # A short ordinal choice refers to the current snapshot, not chat history.
            choice = re.fullmatch(
                r"(?:换|选择|选|试试|试用|用)(?:成)?第?\s*([一二三四五六七八九十]|\d+)\s*(?:个|款)(?:候选|LUT)?(?:[，,。\s]*(?:先)?(?:生成)?预览)?[。！!]?",
                req.text.strip(), re.IGNORECASE,
            )
            if choice:
                value = choice.group(1)
                ordinal = int(value) if value.isdigit() else "一二三四五六七八九十".index(value) + 1
                current_candidates = (context["lut_candidates"] or {}).get("candidates", [])
                if not 1 <= ordinal <= len(current_candidates):
                    plan = Plan(status="clarify", message="没有对应的有效候选，请先检索风格，再选择候选。")
                else:
                    candidate = current_candidates[ordinal - 1]
                    strength = candidate["recommended_strength"]
                    plan = Plan(status="ready", message=f"预览第 {ordinal} 个候选：{candidate['name']}。",
                                search_id=context["lut_candidates"]["search_id"],
                                lut_action={"op": "select", "id": candidate["id"],
                                            "strength": strength if strength is not None else candidate["trial_strength"]})
            else:
                plan = await self.model.plan(context)
            search_result = context.get("lut_candidates")
            if plan.status == "search":
                if not plan.search_intent or plan.adjustments or plan.preset_id or plan.lut_action or plan.memory_actions:
                    raise AppError("model_format", "检索阶段不能同时提交调色操作。", 502)
                search_result = await asyncio.to_thread(self.search.search, owner, plan.search_intent, pid)
                if search_result["status"] != "ok":
                    plan = Plan(status="clarify", message=search_result["message"] or "找到的候选存在偏差，请选择一款或进一步描述需要的效果。")
                else:
                    plan = await self.model.plan({**context, "lut_candidates": search_result, "search_complete": True})
                    if plan.status == "search":
                        raise AppError("model_format", "本轮已检索，请从候选中选择或提出澄清。", 502)
            with self.lock:
                with self.db.connect(write=True) as db:
                    current = self.project(db, pid, owner)
                    self.writable(db, pid)
                    self.revision(current, req.context_revision)
                    if plan.status != "ready" and (
                        plan.adjustments or plan.memory_actions or plan.preset_id or plan.lut_action or plan.search_intent
                    ):
                        raise AppError(
                            "model_format", "模型返回了冲突的操作，请重试。", 502
                        )
                    targets = plan.target_asset_ids
                    # Deterministic resolution for explicit common references.
                    if plan.lut_action and plan.lut_action.op == "select":
                        if not search_result or plan.search_id != search_result["search_id"]:
                            raise AppError("candidate_required", "请先检索当前库中的 LUT，再从有效候选中选择。", 409)
                        self.search.validate(owner, pid, plan.search_id, plan.lut_action.id, db)
                    if plan.search_intent:
                        raise AppError("model_format", "调色阶段不能附带新的检索请求。", 502)
                    if plan.adjustments or plan.preset_id or plan.lut_action:
                        nums = [
                            int(n) for n in re.findall(r"第\s*(\d+)\s*张", req.text)
                        ]
                        if nums:
                            mapping = {a["ordinal"]: a["id"] for a in assets}
                            if any(n not in mapping for n in nums):
                                raise AppError("asset_scope", "指定编号的照片不存在。")
                            targets = [mapping[n] for n in nums]
                        elif re.search(r"全部|所有照片|整组", req.text):
                            targets = [a["id"] for a in assets]
                        elif re.search(r"这一张|这张", req.text) and p["viewed"]:
                            targets = [p["viewed"]]
                        elif not targets:
                            targets = p["selected"]
                        if not targets or not set(targets) <= {a["id"] for a in assets}:
                            raise AppError("asset_scope", "请明确选择要调整的照片。")
                    preferences = dict(current["preferences"])
                    memory_changed = False
                    for action in plan.memory_actions:
                        if action.op == "set":
                            if not re.search(
                                r"记住|记下|保存.*偏好|以后.*喜欢", req.text
                            ):
                                raise AppError(
                                    "memory_explicit",
                                    "保存偏好需要明确说“记住我的偏好”。",
                                )
                            preferences[action.key] = action.value
                            memory_changed = True
                        elif action.op == "clear":
                            if not re.search(r"忘记|清除|删除.*偏好", req.text):
                                raise AppError(
                                    "memory_explicit", "清除偏好需要明确提出。"
                                )
                            preferences.pop(action.key, None)
                            memory_changed = True
                    revision = current["revision"]
                    if memory_changed:
                        db.execute(
                            "UPDATE projects SET preferences_json=?,revision=revision+1 WHERE id=?",
                            (dump(preferences), pid),
                        )
                        revision += 1
                        db.execute(
                            "UPDATE operations SET source_revision=source_revision+1 WHERE project_id=? AND status IN ('ready','previewing')",
                            (pid,),
                        )
                        if plan.lut_action and plan.lut_action.op == "select":
                            # This candidate was validated above. Only this instruction's
                            # explicit memory write may carry its snapshot forward.
                            self.search.carry_after_memory(db, owner, pid, plan.search_id)
                memory_saved = memory_changed
                result = {"status": plan.status, "message": plan.message}
                if plan.status == "ready" and (plan.adjustments or plan.preset_id or plan.lut_action):
                    result = self.preview(
                        pid,
                        owner,
                        PreviewRequest(
                            context_revision=revision,
                            target_asset_ids=targets,
                            preset_id=plan.preset_id,
                            adjustments=plan.adjustments,
                            lut_action=plan.lut_action,
                            search_id=plan.search_id if plan.lut_action and plan.lut_action.op == "select" else None,
                        ),
                        plan.message,
                    )
                elif plan.status == "ready" and plan.memory_actions:
                    result["message"] = (
                        (
                            "已保存本项目偏好："
                            + preferences.get("style_preference", "无")
                        )
                        if memory_changed
                        else (
                            "本项目偏好："
                            + preferences.get("style_preference", "尚未保存偏好")
                        )
                    )
                if memory_changed and result.get("operation_id"):
                    result["message"] = "项目偏好已更新。" + result["message"]
                if search_result:
                    result["lut_search"] = search_result
                self.finish_message(pid, req.request_id, result)
                return result
        except Exception as exc:
            err = (
                exc
                if isinstance(exc, AppError)
                else AppError("model_error", "指令处理失败，请重试。", 502)
            )
            if memory_saved:
                err = AppError(err.code, "项目偏好已更新；但" + err.message, err.status)
            self.finish_message(
                pid,
                req.request_id,
                {"status": "failed", "message": err.message, "code": err.code},
            )
            raise err

    def finish_message(self, pid, rid, result):
        with self.db.connect(write=True) as db:
            # Clearing chat while a request is in-flight must not resurrect it.
            if not db.execute(
                "SELECT 1 FROM messages WHERE project_id=? AND request_id=?", (pid, rid)
            ).fetchone():
                return
            db.execute(
                "UPDATE messages SET response_json=? WHERE project_id=? AND request_id=? AND role='user'",
                (dump(result), pid, rid),
            )
            db.execute(
                "INSERT OR IGNORE INTO messages(id,project_id,request_id,role,content,operation_id,created_at) VALUES (?,?,?,?,?,?,?)",
                (
                    uid(),
                    pid,
                    rid,
                    "assistant",
                    result["message"],
                    result.get("operation_id"),
                    now(),
                ),
            )

    def zip(self, oid, owner):
        with self.db.connect() as db:
            op = self.operation(db, oid, owner)
            if op["status"] not in TERMINAL:
                raise AppError("not_finished", "请等待批次结束后下载 ZIP。", 409)
            items = [
                unpack(i)
                for i in db.execute(
                    "SELECT i.*,a.ordinal,a.name,a.format FROM operation_items i JOIN assets a ON a.id=i.asset_id WHERE operation_id=? ORDER BY a.ordinal",
                    (oid,),
                )
            ]
        if not any(i["status"] == "succeeded" for i in items):
            raise AppError("no_results", "本批次没有可下载的成功结果。")
        path = self.path(f"{op['project_id']}/operations/{oid}/export-{uid()}.zip")
        manifest = []
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as z:
            for item in items:
                filename = (
                    f"{item['ordinal']:02d}-{item['asset_id'][:8]}.{item['format']}"
                )
                if item["status"] == "succeeded":
                    z.write(self.path(item["result"]), filename)
                manifest.append(
                    {
                        "asset_id": item["asset_id"],
                        "ordinal": item["ordinal"],
                        "original_name": item["name"],
                        "status": item["status"],
                        "file": filename if item["status"] == "succeeded" else None,
                        "error": item["error"],
                        "recipe": Recipe.model_validate(item["recipe"]).model_dump(),
                    }
                )
            z.writestr("manifest.json", dump({"operation_id": oid, "items": manifest}))
        return path
