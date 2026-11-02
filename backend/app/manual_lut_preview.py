"""Temporary, local one-photo LUT auditioning. No agent/model calls."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .errors import AppError
from .imaging import inspect, render
from .preview_gallery import PreviewGallery, PreviewPhoto, read_gallery
from .single_pass import catalog, load_catalog_processor


class ManualApply(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    source_run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    photo_id: str = Field(pattern=r"^photo-\d{2}$")
    lut_id: str = Field(pattern=r"^[a-z0-9-]{1,100}$")
    strength: float = Field(gt=0, le=1, strict=True)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ManualPreview:
    def __init__(self, store):
        self.store = Path(store).resolve()
        self.lock = threading.Lock()

    def source(self, run_id, photo_id):
        gallery = read_gallery(self.store, run_id)
        photo = next((p for p in gallery.photos if p.id == photo_id), None)
        if photo is None:
            raise AppError("photo_missing", "所选照片不存在，请刷新页面。", 404)
        folder = (self.store / "runs" / run_id / "files").resolve()
        source = (folder / photo.original_file).resolve()
        if source.parent != folder or not source.is_relative_to(self.store) or not source.is_file():
            raise AppError("photo_path", "无法读取这张照片的原图。", 404)
        return photo, source

    def records(self):
        path = self.store / "manual-tests.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, key, value):
        records = self.records()
        records[key] = value
        self.store.mkdir(parents=True, exist_ok=True)
        temp = self.store / (".manual-" + uuid4().hex)
        temp.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, self.store / "manual-tests.json")

    def options(self, run_id=None, photo_id=None):
        source_hash = None
        if run_id and photo_id:
            _, source = self.source(run_id, photo_id)
            source_hash = digest(source)
        records = list(self.records().values()) if source_hash else []
        result = []
        for row in catalog():
            cases = [r for r in records if r["source_sha256"] == source_hash and
                     r["lut_id"] == row["id"] and r["lut_sha256"] == row["sha256"]]
            cases.sort(key=lambda r:r["created_at"])
            successful = sorted({r["strength"] for r in cases if r["status"] == "completed"})
            result.append({"id": row["id"], "name": row["name"], "tested_strengths": successful,
                           "last_status": cases[-1]["status"] if cases else "untested"})
        return {"items": result, "count": len(result), "successful_count": sum(bool(r["tested_strengths"]) for r in result)}

    def apply(self, request):
        if not self.lock.acquire(blocking=False):
            raise AppError("manual_busy", "正在生成上一张预览，请完成后再试。", 409)
        staging = None
        try:
            photo, source = self.source(request.source_run_id, request.photo_id)
            row = next((r for r in catalog() if r["id"] == request.lut_id), None)
            if row is None:
                raise AppError("lut_unknown", "所选 LUT 不在当前可用库中。", 404)
            source_hash = digest(source)
            key = hashlib.sha256(json.dumps(["manual-preview-v1", source_hash, row["sha256"], request.strength]).encode()).hexdigest()
            prior = self.records().get(key)
            stamp = datetime.now(timezone.utc).isoformat()
            record = {"source_sha256": source_hash, "source_run_id": request.source_run_id,
                      "photo_id": request.photo_id, "lut_id": row["id"], "lut_sha256": row["sha256"],
                      "strength": request.strength, "created_at": stamp}
            try:
                cpu = load_catalog_processor(row)
                if prior and prior["status"] == "completed":
                    try:
                        cached = read_gallery(self.store, prior["run_id"])
                        target = self.store / "runs" / cached.id / "files" / cached.photos[0].result_file
                        if not target.is_symlink() and digest(target) == prior["result_sha256"]:
                            return {"run_id": cached.id, "cache_hit": True}
                    except (AppError, OSError, ValueError):
                        pass  # Missing cache: regenerate from the original.
                run_id = uuid4().hex
                runs = self.store / "runs"
                staging = runs / ("." + run_id)
                files = staging / "files"
                files.mkdir(parents=True)
                kind = inspect(source)["format"]
                original = files / f"01-original.{kind}"
                target = files / f"01-graded.{kind}"
                shutil.copyfile(source, original)
                recipe = {"lut": {"id": row["id"], "name": row["name"], "sha256": row["sha256"], "strength": request.strength}}
                render(original, target, recipe, lut_processor=cpu)
                info = inspect(target)
                if digest(source) != source_hash or digest(original) != source_hash:
                    raise AppError("photo_changed", "原图发生变化，请重新载入后再试。", 409)
                result = PreviewGallery(id=run_id, created_at=stamp, photos=[PreviewPhoto(
                    id="photo-01", name=photo.name, lut_name=row["name"], strength=request.strength,
                    width=info["width"], height=info["height"], original_file=original.name, result_file=target.name)])
                (staging / "gallery.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
                record.update(status="completed", run_id=run_id, result_sha256=digest(target))
                (staging / "manual-test.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
                staging.rename(runs / run_id)
                # Leave current.json untouched: auditioning must not change the
                # source batch or interrupt another photo selected in the UI.
                self.save(key, record)
                return {"run_id": run_id, "cache_hit": False}
            except Exception as exc:
                message = exc.message if isinstance(exc, AppError) else "照片预览生成失败，请检查源图或更换 LUT 后重试。"
                self.save(key, {**record, "status": "failed", "message": message})
                if isinstance(exc, AppError):
                    raise
                raise AppError("manual_render", message, 500) from exc
        finally:
            if staging and staging.exists():
                shutil.rmtree(staging)
            self.lock.release()
