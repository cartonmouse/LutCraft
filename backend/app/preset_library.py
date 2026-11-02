import sqlite3
from .db import uid, now, dump, unpack
from .errors import AppError
from .schemas import Recipe


class PresetLibrary:
    def __init__(self, service):
        self.service = service

    @staticmethod
    def public(row):
        return {**{k: v for k, v in row.items() if k not in ("owner", "deleted_at")},
                "recipe": Recipe.model_validate(row["recipe"]).model_dump()}

    def get(self, db, preset_id, owner):
        row = unpack(db.execute("SELECT * FROM personal_presets WHERE id=? AND owner=? AND deleted_at IS NULL",
                                (preset_id, owner)).fetchone())
        if not row:
            raise AppError("preset_not_found", "个人预设不存在或不属于当前浏览器会话。", 404)
        return row

    def list(self, owner):
        with self.service.db.connect() as db:
            return [self.public(unpack(r)) for r in db.execute(
                "SELECT * FROM personal_presets WHERE owner=? AND deleted_at IS NULL ORDER BY created_at DESC", (owner,))]

    def save(self, owner, req):
        s = self.service
        try:
            with s.lock, s.db.connect(write=True) as db:
                s.project(db, req.project_id, owner)
                s.writable(db, req.project_id)
                if db.execute("SELECT 1 FROM operations WHERE project_id=? AND status IN ('ready','previewing')", (req.project_id,)).fetchone():
                    raise AppError("preset_pending", "请先应用或放弃待确认预览，再保存已应用效果。", 409)
                a = unpack(db.execute("SELECT * FROM assets WHERE id=? AND project_id=?", (req.asset_id, req.project_id)).fetchone())
                if not a:
                    raise AppError("asset_scope", "来源照片不属于当前影集。", 404)
                if a["revision"] != req.asset_revision:
                    raise AppError("stale_state", "照片效果已变化，请刷新后再保存预设。", 409)
                recipe = s.luts.update_recipe(db, a["recipe"], None, owner)
                pid, stamp = uid(), now()
                db.execute("""INSERT INTO personal_presets(id,owner,name,recipe_json,lut_id,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?)""", (pid, owner, req.name, dump(recipe), recipe["lut"]["id"] if recipe["lut"] else None, stamp, stamp))
                return self.public(self.get(db, pid, owner))
        except sqlite3.IntegrityError as exc:
            raise AppError("preset_name", "已有同名个人预设，请换一个名称。", 409) from exc

    def rename(self, owner, pid, req):
        try:
            with self.service.db.connect(write=True) as db:
                row = self.get(db, pid, owner)
                if row["revision"] != req.revision:
                    raise AppError("stale_state", "预设已变化，请刷新列表后重试。", 409)
                db.execute("UPDATE personal_presets SET name=?,revision=revision+1,updated_at=? WHERE id=?", (req.name, now(), pid))
                return self.public(self.get(db, pid, owner))
        except sqlite3.IntegrityError as exc:
            raise AppError("preset_name", "已有同名个人预设，请换一个名称。", 409) from exc

    def delete(self, owner, pid):
        with self.service.db.connect(write=True) as db:
            self.get(db, pid, owner)
            db.execute("UPDATE personal_presets SET deleted_at=?,revision=revision+1 WHERE id=?", (now(), pid))
        return {"status": "deleted"}
