"""Prepared sample looks and explicit, local application to a user's photo."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import threading
from uuid import uuid4

import pyvips

from .errors import AppError
from .imaging import inspect, render
from .preview_gallery import PreviewGallery, PreviewPhoto
from .single_pass import catalog, load_catalog_processor

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STYLE_STORE = ROOT / "data/style-gallery"
MAX_UPLOAD = 10 * 1024 * 1024
BUILD_ID = re.compile(r"^[a-f0-9]{32}$")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class StyleGallery:
    def __init__(self, store=DEFAULT_STYLE_STORE, preview_store=None, lock=None):
        self.store = Path(store).resolve()
        self.preview_store = Path(preview_store).resolve() if preview_store else None
        self.lock = lock if lock is not None else threading.Lock()

    def read(self, build_id=None):
        if build_id is None:
            pointer = self.store / "current.json"
            if not pointer.exists():
                return None
            build_id = json.loads(pointer.read_text())["id"]
        if not isinstance(build_id, str) or not BUILD_ID.fullmatch(build_id):
            raise AppError("style_missing", "这组风格预览不存在。", 404)
        folder = self.store / "builds" / build_id
        if folder.is_symlink() or not folder.is_dir():
            raise AppError("style_missing", "这组风格预览不存在。", 404)
        manifest = folder / "manifest.json"
        if manifest.is_symlink():
            raise AppError("style_missing", "这组风格预览不存在。", 404)
        value = json.loads(manifest.read_text())
        if value["id"] != build_id:
            raise AppError("style_invalid", "风格预览信息不完整。", 503)
        return value

    def asset(self, build_id, filename):
        value = self.read(build_id)
        if filename not in value["assets"] or Path(filename).name != filename:
            raise AppError("asset_missing", "预览图片不存在。", 404)
        folder = (self.store / "builds" / build_id / "files").resolve()
        path = folder / filename
        if path.is_symlink() or path.resolve().parent != folder or not folder.is_relative_to(self.store) or not path.is_file():
            raise AppError("asset_missing", "预览图片不存在。", 404)
        return path

    def public(self):
        value = self.read()
        if value is None:
            return {"status": "waiting", "items": [], "scenes": []}
        prefix = f'/api/styles/{value["id"]}/files/'
        scenes = [{"id": s["id"], "name": s["name"], "kind": s.get("kind", "user-provided"),
                   "original_url": prefix+s["original"], "thumbnail_url": prefix+s["thumbnail"]}
                  for s in value["scenes"]]
        items = []
        for row in value["items"]:
            item = {k: row[k] for k in ("id", "label", "collection", "category", "tags")}
            sample_id = row.get("sample_id", scenes[0]["id"] if scenes else None)
            item["sample"] = next((s for s in scenes if s["id"] == sample_id), None)
            # Keep unfinished styles in the build for later configuration, but
            # only publish cards with a full-strength sample and thumbnail.
            cover = row["previews"].get(sample_id, {}).get("100", {})
            if not item["sample"] or not cover.get("image") or not cover.get("thumbnail"):
                continue
            item["availability"] = row.get("availability", "ready")
            item["preview_status"] = "ready" if item["sample"] and row["previews"] else "pending"
            item["availability_note"] = row.get("availability_note", "")
            item["previews"] = {scene: {strength: {"url": prefix+files["image"], "thumbnail_url": prefix+files["thumbnail"]}
                                       for strength, files in strengths.items()}
                                for scene, strengths in row["previews"].items()}
            if row.get("story"):
                story = row["story"]
                item["story"] = {k: story[k] for k in ("headline", "description", "traits")}
                item["story"]["examples"] = [
                    {"title": e["title"], "caption": e["caption"], "url": prefix+e["image"], "strength": 100}
                    for e in story["examples"]]
            items.append(item)
        return {"status": "ready", "id": value["id"], "mode": value.get("mode", "shared-samples"), "scenes": scenes, "items": items,
                "strengths": value["strengths"], "catalog_count": value["catalog_count"]}

    def selected(self, build_id, lut_id, strength):
        if strength not in (.5, 1):
            raise AppError("strength_invalid", "请选择 50% 或 100% 强度。", 422)
        manifest = self.read(build_id)
        selected = next((r for r in manifest["items"] if r["id"] == lut_id), None)
        if selected is None:
            raise AppError("style_missing", "所选风格不在这组预览中。", 404)
        if selected.get("availability", "ready") != "ready":
            raise AppError("style_unavailable", "此 LUT 已收录，照片适配尚未完成。", 409)
        row = next((r for r in catalog() if r["id"] == lut_id), None)
        if row is None or row["sha256"] != selected["lut_sha256"]:
            raise AppError("style_changed", "此风格已更新，请重新制作预览后再使用。", 409)
        return row

    def apply(self, source, build_id, lut_id, strength, name):
        if not self.lock.acquire(blocking=False):
            raise AppError("style_busy", "上一张照片还在处理中，请稍后再试。", 409)
        staging = None
        try:
            row = self.selected(build_id, lut_id, strength)
            meta = inspect(source)
            original_hash = digest(source)
            cpu = load_catalog_processor(row)
            run_id = uuid4().hex
            runs = self.preview_store / "runs"
            staging = runs / ("."+run_id)
            files = staging / "files"
            files.mkdir(parents=True)
            original = files / f'01-original.{meta["format"]}'
            result = files / f'01-graded.{meta["format"]}'
            shutil.copyfile(source, original)
            recipe = {"lut": {"id": row["id"], "name": row["name"], "sha256": row["sha256"], "strength": strength}}
            render(original, result, recipe, lut_processor=cpu)
            info = inspect(result)
            if digest(original) != original_hash:
                raise AppError("source_changed", "原图校验失败，请重新选择照片。", 409)
            gallery = PreviewGallery(id=run_id, created_at=datetime.now(timezone.utc).isoformat(), photos=[PreviewPhoto(
                id="photo-01", name=name[:200] or "我的照片", lut_name=row["name"], strength=strength,
                width=info["width"], height=info["height"], original_file=original.name, result_file=result.name)])
            (staging / "gallery.json").write_text(gallery.model_dump_json(indent=2))
            (staging / "style-application.json").write_text(json.dumps({"build_id": build_id, "lut_id": lut_id,
                "lut_sha256": row["sha256"], "strength": strength, "source_sha256": original_hash,
                "result_sha256": digest(result), "max_edge": 2560}, indent=2))
            staging.rename(runs / run_id)
            pointer = self.preview_store / (".current-"+run_id)
            pointer.write_text(json.dumps({"id": run_id}))
            os.replace(pointer, self.preview_store / "current.json")
            return {"run_id": run_id, "url": f'/results?run={run_id}', "width": info["width"], "height": info["height"],
                    "original_url": f'/api/previews/{run_id}/files/{original.name}',
                    "result_url": f'/api/previews/{run_id}/files/{result.name}'}
        except pyvips.Error as exc:
            raise AppError("image_invalid", "无法读取这张照片，请选择完整的 JPEG 或 PNG 图片。", 422) from exc
        finally:
            if staging is not None and staging.exists():
                shutil.rmtree(staging)
            self.lock.release()
