import hashlib
import math
import shlex
import shutil
from functools import lru_cache
from pathlib import Path

from .db import uid, now, unpack
from .errors import AppError
from .schemas import LutReference, Recipe

try:
    import PyOpenColorIO as ocio
    import numpy as np
except (ImportError, OSError):
    ocio = np = None

MAX_BYTES = 10 * 1024 * 1024


def engine_status():
    return {"available": ocio is not None and np is not None,
            "version": ocio.__version__ if ocio else None}


def require_engine():
    if not engine_status()["available"]:
        raise AppError("lut_engine", "LUT 引擎未就绪，请重新运行环境安装脚本。基础调色仍可使用。", 503)


def inspect_cube(data, *, bundled=False):
    if len(data) > MAX_BYTES:
        raise AppError("lut_size", "LUT 文件不能超过 10 MB。")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError as exc:
        raise AppError("lut_format", "LUT 必须是 UTF-8 文本格式的 .cube 文件。") from exc
    headers, rows = {}, 0
    for number, line in enumerate(text.splitlines(), 1):
        # A TITLE is metadata only; never interpret it as a path or instruction.
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            parts = shlex.split(line, comments=True) if line.startswith("TITLE") else line.split("#", 1)[0].split()
            if not parts:
                continue
            key = parts[0]
            if key in ("TITLE", "LUT_3D_SIZE", "DOMAIN_MIN", "DOMAIN_MAX"):
                if rows or key in headers:
                    raise ValueError("重复或位于数据之后的头部")
                if key == "TITLE":
                    if len(parts) != 2:
                        raise ValueError("TITLE 需要一个名称")
                    headers[key] = parts[1]
                elif key == "LUT_3D_SIZE":
                    sizes = ("13", "16", "17", "25", "32", "33", "40", "64", "65") if bundled else ("13", "17", "32", "33", "65")
                    if len(parts) != 2 or parts[1] not in sizes:
                        raise ValueError("不支持此 3D LUT 网格尺寸")
                    headers[key] = int(parts[1])
                else:
                    expected = 0.0 if key == "DOMAIN_MIN" else 1.0
                    if len(parts) != 4 or any(float(v) != expected for v in parts[1:]):
                        raise ValueError("只支持 0–1 输入域")
                    headers[key] = parts[1:]
            else:
                if "LUT_3D_SIZE" not in headers or len(parts) != 3:
                    raise ValueError("未知指令、缺少 3D 尺寸或数据行无效；不支持 1D LUT")
                values = [float(v) for v in parts]
                if any(not math.isfinite(v) or abs(v) > 3.4e38 for v in values):
                    raise ValueError("数据必须为有限 float32 数值")
                rows += 1
                if rows > headers["LUT_3D_SIZE"] ** 3:
                    raise ValueError("数据行过多")
        except ValueError as exc:
            raise AppError("lut_format", f"LUT 第 {number} 行无效：{exc}。") from exc
    size = headers.get("LUT_3D_SIZE")
    if size is None or rows != size ** 3:
        raise AppError("lut_format", "LUT 数据行数必须等于网格尺寸的三次方。")
    return {"grid_size": size, "title": headers.get("TITLE", "")}


@lru_cache(maxsize=8)
def processor(path, digest, version):
    require_engine()
    try:
        transform = ocio.FileTransform(src=path, interpolation=ocio.INTERP_TETRAHEDRAL)
        return ocio.Config.CreateRaw().getProcessor(transform).getDefaultCPUProcessor()
    except Exception as exc:
        raise AppError("lut_processor", "LUT 引擎无法读取该文件，请检查 .cube 格式。") from exc


class LutLibrary:
    def __init__(self, db, path):
        self.db, self.path = db, path
        self.metadata = None

    @staticmethod
    def public(row):
        return {k: v for k, v in row.items() if k not in ("owner", "file_ref")}

    def get(self, db, lid, owner):
        row = unpack(db.execute("SELECT * FROM luts WHERE id=? AND owner=?", (lid, owner)).fetchone())
        if not row:
            raise AppError("lut_not_found", "LUT 不存在或不属于当前浏览器会话。", 404)
        return row

    def list(self, owner):
        with self.db.connect() as db:
            items = [self.public(dict(r)) for r in db.execute(
                "SELECT * FROM luts WHERE owner=? ORDER BY created_at DESC", (owner,))]
            if self.metadata:
                for item in items:
                    profile = self.metadata.get(owner, item["id"], db)
                    item["profile"] = profile
            return items

    def upload(self, owner, filename, data, name="", color_space="srgb", metadata=None):
        require_engine()
        if Path(filename).suffix.lower() != ".cube":
            raise AppError("lut_format", "请选择 .cube 文件。")
        meta = inspect_cube(data)
        name = name.strip() or meta["title"][:80].strip() or Path(filename).stem[:80]
        if not 1 <= len(name) <= 80:
            raise AppError("lut_name", "LUT 名称需要 1–80 个字符。")
        digest = hashlib.sha256(data).hexdigest()
        if self.metadata:
            self.metadata.import_values(metadata, digest)
        with self.db.connect(write=True) as db:
            previous = db.execute("SELECT * FROM luts WHERE owner=? AND sha256=?", (owner, digest)).fetchone()
            if previous:
                if self.metadata:
                    self.metadata.propose_import(db, dict(previous), metadata)
                return {**self.public(dict(previous)), "import_status": "existing"}
            lid = uid()
            ref = f"luts/{lid}/source.cube"
            file = self.path(ref)
            file.parent.mkdir(parents=True)
            try:
                file.write_bytes(data)
                processor(str(file), digest, ocio.__version__)
                db.execute("""INSERT INTO luts
                    (id,owner,name,original_filename,file_ref,sha256,grid_size,input_space,output_space,byte_size,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (lid, owner, name, Path(filename).name[:200], ref, digest, meta["grid_size"], "srgb", "srgb", len(data), now()))
                row = self.public(self.get(db, lid, owner))
                if self.metadata:
                    self.metadata.ensure(db, row, color_space, metadata)
            except Exception:
                shutil.rmtree(file.parent, ignore_errors=True)
                raise
        if self.metadata:
            try:
                self.metadata.enqueue(owner, lid)
            except AppError:
                pass  # Import succeeded; analysis can be retried independently.
        return {**row, "import_status": "imported"}

    def reference(self, db, lid, owner, strength):
        row = self.get(db, lid, owner)
        return LutReference(id=lid, name=row["name"], sha256=row["sha256"], strength=strength).model_dump()

    def resolve(self, db, reference, owner):
        row = self.get(db, reference["id"], owner)
        if row["sha256"] != reference["sha256"]:
            raise AppError("lut_changed", "LUT 摘要不匹配，请重新选择 LUT。", 409)
        file = self.path(row["file_ref"])
        if not file.is_file():
            raise AppError("lut_missing", "LUT 文件丢失，无法重新处理；已生成的图片仍可下载。", 409)
        if file.stat().st_size > MAX_BYTES or hashlib.sha256(file.read_bytes()).hexdigest() != row["sha256"]:
            raise AppError("lut_changed", "LUT 文件内容已变化，已停止本次处理。", 409)
        require_engine()
        return processor(str(file), row["sha256"], ocio.__version__)

    def update_recipe(self, db, recipe, action, owner):
        r = Recipe.model_validate(recipe).model_dump()
        if action:
            if action.op == "clear":
                r["lut"] = None
            elif action.op == "select":
                if self.metadata:
                    profile = self.metadata.get(owner, action.id, db)
                    if profile["compatibility"] != "confirmed" or not profile["enabled"]:
                        raise AppError("lut_compatibility", "请先确认此 LUT 的 sRGB 使用条件并启用它。", 409)
                r["lut"] = self.reference(db, action.id, owner, 1 if action.strength is None else action.strength)
            elif not r["lut"]:
                raise AppError("lut_required", "请先为所选照片选择 LUT，再调整强度。")
            else:
                r["lut"]["strength"] = action.strength
        if r["lut"]:
            self.resolve(db, r["lut"], owner)
        return Recipe.model_validate(r).model_dump()
