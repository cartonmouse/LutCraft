"""Local, read-only preview handoff. Only Codex/the runtime writes galleries."""
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .errors import AppError
from .imaging import inspect
from .single_pass import read_input

DEFAULT_STORE = Path(__file__).resolve().parents[2] / "data/lut-preview"
RUN_ID = re.compile(r"^[a-f0-9]{32}$")


class PreviewPhoto(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str = Field(pattern=r"^photo-\d{2}$")
    name: str = Field(min_length=1, max_length=200)
    lut_name: str = Field(min_length=1, max_length=100)
    strength: float = Field(gt=0, le=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    original_file: str = Field(pattern=r"^\d{2}-original\.(jpg|png)$")
    result_file: str = Field(pattern=r"^\d{2}-graded\.(jpg|png)$")


class PreviewGallery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    photos: list[PreviewPhoto] = Field(min_length=1, max_length=10)
    created_at: str


def publish_jobs(job_dirs, store=DEFAULT_STORE, names=None):
    """Copy explicitly supplied finished jobs; do not discover other task data."""
    store = Path(store).resolve()
    run_id = uuid4().hex
    runs = store / "runs"
    staging = runs / ("." + run_id)
    files = staging / "files"
    files.mkdir(parents=True)
    photos = []
    try:
        for job_dir in job_dirs:
            job = Path(job_dir).resolve()
            _, originals = read_input(job / "input/invocation.json")
            result = json.loads((job / "output/result.json").read_text())
            if result.get("status") != "completed" or len(result.get("photos", [])) != len(originals):
                raise AppError("preview_incomplete", "当前任务尚无完整调色结果。")
            seen = set()
            for photo in result["photos"]:
                source_index = photo["index"]
                if not isinstance(source_index, int) or not 1 <= source_index <= len(originals) or source_index in seen:
                    raise AppError("preview_index", "结果与原图无法对应。")
                seen.add(source_index)
                source = (job / "output" / photo["filename"]).resolve()
                if source.parent != (job / "output").resolve() or not source.is_file():
                    raise AppError("preview_path", "结果图片路径无效。")
                if hashlib.sha256(source.read_bytes()).hexdigest() != photo["sha256"]:
                    raise AppError("preview_changed", "结果文件校验失败。")
                original = originals[source_index - 1]
                original_meta, result_meta = inspect(original), inspect(source)
                index = len(photos) + 1
                original_name = f"{index:02d}-original.{original_meta['format']}"
                result_name = f"{index:02d}-graded.{result_meta['format']}"
                shutil.copyfile(original, files / original_name)
                shutil.copyfile(source, files / result_name)
                photos.append(PreviewPhoto(id=f"photo-{index:02d}", name=f"照片 {index:02d}",
                    lut_name=result["lut"]["name"], strength=result["lut"]["strength"],
                    width=result_meta["width"], height=result_meta["height"],
                    original_file=original_name, result_file=result_name))
        if names is not None:
            if len(names) != len(photos):
                raise AppError("preview_names", "照片名称数量与结果不一致。")
            for photo, name in zip(photos, names):
                photo.name = name
        gallery = PreviewGallery.model_validate({"id": run_id, "photos": [p.model_dump() for p in photos],
                                                "created_at": datetime.now(timezone.utc).isoformat()})
        (staging / "gallery.json").write_text(gallery.model_dump_json(indent=2))
        staging.rename(runs / run_id)
        pointer = store / (".current-" + run_id)
        pointer.write_text(json.dumps({"id": run_id}))
        os.replace(pointer, store / "current.json")
        return {"id": run_id, "photo_count": len(photos), "url": f"http://127.0.0.1:4175/?run={run_id}"}
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def read_gallery(store=DEFAULT_STORE, run_id=None):
    store = Path(store).resolve()
    if run_id is None:
        pointer = store / "current.json"
        if not pointer.exists():
            return None
        run_id = json.loads(pointer.read_text()).get("id", "")
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise AppError("preview_missing", "预览不存在。", 404)
    directory = (store / "runs" / run_id).resolve()
    if directory.parent != (store / "runs").resolve() or not (directory / "gallery.json").is_file():
        raise AppError("preview_missing", "预览不存在。", 404)
    gallery = PreviewGallery.model_validate_json((directory / "gallery.json").read_text())
    if gallery.id != run_id:
        raise AppError("preview_invalid", "预览信息无效。", 404)
    return gallery


def list_galleries(store=DEFAULT_STORE, limit=20, offset=0):
    """List published batches only. Staging folders and other jobs stay private."""
    store = Path(store).resolve()
    runs = store / "runs"
    galleries, unavailable = [], 0
    if runs.exists():
        for directory in runs.iterdir():
            if not RUN_ID.fullmatch(directory.name) or directory.is_symlink() or not directory.is_dir():
                continue
            try:
                item = read_gallery(store, directory.name)
                date = datetime.fromisoformat(item.created_at.replace("Z", "+00:00"))
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                galleries.append((date.timestamp(), item.id, item))
            except (AppError, OSError, ValueError, OverflowError):
                unavailable += 1
    galleries.sort(key=lambda row: (row[0], row[1]), reverse=True)
    try:
        current = read_gallery(store)
        current_id = current.id if current else None
    except (AppError, OSError, ValueError):
        current_id = None
    end = offset + limit
    return {"galleries": [row[2] for row in galleries[offset:end]], "total": len(galleries),
            "next_offset": end if end < len(galleries) else None,
            "current_id": current_id, "unavailable_count": unavailable}
