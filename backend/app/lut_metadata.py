"""Owned metadata, immutable provenance and restartable analysis/index jobs."""
import hashlib
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pydantic import ValidationError
from .config import ROOT
from .db import dump, now, uid, unpack
from .errors import AppError
from .library_schemas import Metadata
from .lut_analysis import analyze, VERSION

log = logging.getLogger(__name__)


def search_text(name, metadata, analysis=None):
    return "\n".join([name, metadata["description"], metadata["category"],
                      " ".join(metadata["tags"]), " ".join(metadata["aliases"]),
                      " ".join(metadata["use_cases"]), (analysis or {}).get("description", "")])[:4000]


class LutMetadata:
    def __init__(self, service, embedding):
        self.s, self.embedding = service, embedding
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lut-index")
        self.lock = threading.RLock()
        self.closed = False
        self.catalog = {}
        path = ROOT / "lut-library/catalog.json"
        if path.exists():
            try:
                self.catalog = {r["original_sha256"]: r for r in json.loads(path.read_text())["items"]}
            except (ValueError, KeyError, TypeError):
                log.warning("LUT catalog could not be read; manual metadata remains available")
        with self.s.db.connect(write=True) as db:
            for row in db.execute("SELECT * FROM luts").fetchall():
                self.ensure(db, dict(row), "legacy")
            # The application owns a single process, as does the image queue.
            db.execute("UPDATE lut_index_jobs SET status='queued',updated_at=? WHERE status='running'", (now(),))
        self.pool.submit(self.drain)

    def close(self):
        self.closed = True
        self.pool.shutdown(wait=True)

    def import_values(self, raw, digest):
        if not raw:
            return {}, {}
        if not isinstance(raw, dict) or len(dump(raw)) > 24000:
            raise AppError("metadata_format", "元信息必须是有限大小的 JSON 对象。")
        declared = raw.get("original_sha256") or raw.get("sha256")
        if declared and declared != digest:
            raise AppError("metadata_digest", "元信息与 CUBE 文件摘要不匹配。")
        values = {k: raw[k] for k in Metadata.model_fields if k in raw}
        values.setdefault("description", raw.get("style_zh", ""))
        if raw.get("input_profile"):
            values.setdefault("compatibility_basis", str(raw["input_profile"])[:800])
        if raw.get("license"):
            values.setdefault("license_note", dump(raw["license"])[:1200])
        # Sidecars can describe compatibility; only explicit user confirmation enables it.
        values.pop("input_space", None)
        values.pop("output_space", None)
        try:
            cleaned = Metadata.model_validate(values).model_dump()
        except ValidationError as exc:
            raise AppError("metadata_format", "元信息字段或长度无效。") from exc
        return cleaned, {"catalog_id": str(raw.get("id", ""))[:100],
                         "file_sha256": digest, "source": "imported_metadata"}

    def ensure(self, db, lut, confirmation="unknown", raw=None):
        if db.execute("SELECT 1 FROM lut_profiles WHERE lut_id=?", (lut["id"],)).fetchone():
            return
        raw = {**self.catalog.get(lut["sha256"], {}), **(raw or {})}
        values, origin = self.import_values(raw, lut["sha256"])
        values = Metadata.model_validate(values).model_dump()
        publisher = values["publisher"]
        if publisher and lut["name"].casefold().startswith(publisher.casefold() + " "):
            alias = lut["name"][len(publisher):].strip()
            if alias and alias not in values["aliases"]:
                values["aliases"] = [*values["aliases"], alias][:24]
        evidence = {k: {"source": "publisher" if k in ("publisher", "license_note", "source_page") else "file",
                        "reference": values.get("source_page", ""), "review": "imported", "at": now()}
                    for k, v in values.items() if v not in ("", [], None, "unknown")}
        evidence["origin"] = origin
        if confirmation in ("srgb", "legacy"):
            values.update(input_space="srgb", output_space="srgb")
            values["compatibility_basis"] = values["compatibility_basis"] or (
                "历史导入时的 sRGB 声明；未进行作者或测量认证。" if confirmation == "legacy"
                else "用户根据提供方说明确认输入、输出适用于 sRGB 照片。")
            evidence["compatibility"] = {"source": "user", "review": "legacy_declaration" if confirmation == "legacy" else "accepted", "at": now()}
        db.execute("""INSERT INTO lut_profiles(lut_id,compatibility,metadata_json,evidence_json,updated_at)
                      VALUES (?,?,?,?,?)""", (lut["id"], "confirmed" if confirmation in ("srgb", "legacy") else "unknown",
                                             dump(values), dump(evidence), now()))

    def propose_import(self, db, lut, raw):
        if not raw:
            return
        values, _ = self.import_values(raw, lut["sha256"])
        profile = self.get(lut["owner"], lut["id"], db)
        suggestions, evidence = profile["suggestions"], profile["evidence"]
        origins = evidence.setdefault("suggestion_sources", {})
        for key, value in values.items():
            if value not in ("", [], None, "unknown") and value != profile["metadata"].get(key):
                suggestions[key] = value
                origins[key] = "file"
        db.execute("UPDATE lut_profiles SET suggestions_json=?,evidence_json=? WHERE lut_id=?",
                   (dump(suggestions), dump(evidence), lut["id"]))

    def get(self, owner, lid, db=None):
        if db is None:
            with self.s.db.connect() as conn:
                return self.get(owner, lid, conn)
        lut = self.s.luts.get(db, lid, owner)
        row = unpack(db.execute("SELECT * FROM lut_profiles WHERE lut_id=?", (lid,)).fetchone())
        job = unpack(db.execute("SELECT * FROM lut_index_jobs WHERE lut_id=? ORDER BY created_at DESC LIMIT 1", (lid,)).fetchone())
        index = db.execute("SELECT revision,text_hash FROM lut_embeddings WHERE lut_id=? AND fingerprint=?",
                           (lid, self.embedding.fingerprint)).fetchone()
        indexed = bool(index and index[0] == row["revision"] and index[1] == hashlib.sha256(
            search_text(lut["name"], row["metadata"], row["analysis"]).encode()).hexdigest())
        return {**row, "name": lut["name"], "sha256": lut["sha256"],
                "technical": {"grid_size": lut["grid_size"], "byte_size": lut["byte_size"], "input_domain": [0, 1]},
                "index_status": "ready" if indexed else "pending" if self.embedding.configured else "unconfigured",
                "job": self.public_job(job) if job else None}

    @staticmethod
    def public_job(job):
        return {k: v for k, v in job.items() if k not in ("owner", "fingerprint")}

    def patch(self, owner, lid, req):
        with self.s.db.connect(write=True) as db:
            profile = self.get(owner, lid, db)
            if req.revision != profile["revision"]:
                raise AppError("metadata_stale", "元信息已更新，请重新加载后保存。", 409)
            metadata, evidence = profile["metadata"], profile["evidence"]
            updates = req.metadata.model_dump(exclude_unset=True)
            for key in req.accept_suggestions:
                if key not in Metadata.model_fields or key not in profile["suggestions"]:
                    raise AppError("metadata_suggestion", "该字段没有可接受的建议。")
                if key not in updates:
                    metadata[key] = profile["suggestions"][key]
                    evidence[key] = {"source": evidence.get("suggestion_sources", {}).get(key, "measured"), "review": "accepted", "at": now(), "version": VERSION}
            for key, value in updates.items():
                metadata[key] = value
                evidence[key] = {"source": "user", "review": "accepted", "at": now()}
            metadata = Metadata.model_validate(metadata).model_dump()
            compatibility = req.compatibility or profile["compatibility"]
            if compatibility == "confirmed" and (metadata["input_space"] != "srgb" or metadata["output_space"] != "srgb" or not metadata["compatibility_basis"]):
                raise AppError("metadata_space", "确认兼容前请填写 sRGB 输入/输出及确认依据。")
            if metadata["recommended_strength"] is not None and not metadata["strength_basis"]:
                raise AppError("metadata_strength", "推荐强度需要填写依据，也可留空使用试用档位。")
            if req.compatibility is not None:
                evidence["compatibility"] = {"source": "user", "review": "accepted", "at": now()}
            db.execute("""UPDATE lut_profiles SET metadata_json=?, evidence_json=?, enabled=?, compatibility=?,
                          revision=revision+1,updated_at=? WHERE lut_id=?""",
                       (dump(metadata), dump(evidence), profile["enabled"] if req.enabled is None else int(req.enabled), compatibility, now(), lid))
        self.enqueue(owner, lid)
        return self.get(owner, lid)

    def enqueue(self, owner, lid):
        with self.lock, self.s.db.connect(write=True) as db:
            profile = self.get(owner, lid, db)
            existing = db.execute("SELECT id FROM lut_index_jobs WHERE lut_id=? AND revision=? AND fingerprint=? AND status IN ('queued','running')",
                                  (lid, profile["revision"], self.embedding.fingerprint)).fetchone()
            if existing:
                return {"id": existing[0], "status": "queued"}
            if db.execute("SELECT count(*) FROM lut_index_jobs WHERE status IN ('queued','running')").fetchone()[0] >= 100:
                raise AppError("index_busy", "分析队列已满，文件已保存，请稍后重试分析。", 429)
            jid = uid()
            db.execute("INSERT INTO lut_index_jobs(id,lut_id,owner,revision,fingerprint,status,stage,created_at,updated_at) VALUES (?,?,?,?,?,'queued','analysis',?,?)",
                       (jid, lid, owner, profile["revision"], self.embedding.fingerprint, now(), now()))
        if not self.closed:
            self.pool.submit(self.drain)
        return {"id": jid, "status": "queued"}

    def job(self, owner, jid):
        with self.s.db.connect() as db:
            row = unpack(db.execute("SELECT * FROM lut_index_jobs WHERE id=? AND owner=?", (jid, owner)).fetchone())
            if not row:
                raise AppError("not_found", "分析任务不存在。", 404)
            return self.public_job(row)

    def drain(self):
        while not self.closed:
            with self.s.db.connect(write=True) as db:
                job = unpack(db.execute("SELECT * FROM lut_index_jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone())
                if not job:
                    return
                db.execute("UPDATE lut_index_jobs SET status='running',attempts=attempts+1,updated_at=? WHERE id=?", (now(), job["id"]))
            try:
                self.run(job)
            except Exception as exc:
                message = exc.message if isinstance(exc, AppError) else "分析未完成，请重试。"
                retry = isinstance(exc, AppError) and exc.code == "embedding_network" and job["attempts"] < 1
                with self.s.db.connect(write=True) as db:
                    db.execute("UPDATE lut_index_jobs SET status=?,error=?,updated_at=? WHERE id=?",
                               ("queued" if retry else "failed", message, now(), job["id"]))
                if retry:
                    time.sleep(.5)

    def run(self, job):
        profile = self.get(job["owner"], job["lut_id"])
        if profile["revision"] != job["revision"] or job["fingerprint"] != self.embedding.fingerprint:
            return self.finish(job, "stale", "元信息或索引配置已变化，请重新分析。")
        if profile["compatibility"] != "confirmed":
            return self.finish(job, "ready", "先确认输入和输出色彩空间，再分析效果。", "awaiting_compatibility")
        with self.s.db.connect() as db:
            cpu = self.s.luts.resolve(db, self.s.luts.reference(db, job["lut_id"], job["owner"], 1), job["owner"])
        analysis = analyze(cpu)
        with self.s.db.connect(write=True) as db:
            current_profile = self.get(job["owner"], job["lut_id"], db)
            suggestions = current_profile["suggestions"]
            for key in ("description", "tags"):
                if current_profile["evidence"].get("suggestion_sources", {}).get(key) != "file":
                    suggestions[key] = analysis[key]
            db.execute("UPDATE lut_profiles SET analysis_json=?,suggestions_json=? WHERE lut_id=? AND revision=?",
                       (dump(analysis), dump(suggestions), job["lut_id"], job["revision"]))
            db.execute("UPDATE lut_index_jobs SET stage='embedding',updated_at=? WHERE id=?", (now(), job["id"]))
        if not self.embedding.configured:
            return self.finish(job, "ready", None, "keyword_ready")
        text = search_text(profile["name"], profile["metadata"], analysis)
        vector = self.embedding.embed_documents([text])[0]
        with self.s.db.connect(write=True) as db:
            current = db.execute("SELECT revision FROM lut_profiles WHERE lut_id=?", (job["lut_id"],)).fetchone()[0]
            if current != job["revision"]:
                db.execute("UPDATE lut_index_jobs SET status='stale',updated_at=? WHERE id=?", (now(), job["id"]))
                return
            db.execute("""INSERT OR REPLACE INTO lut_embeddings(lut_id,fingerprint,revision,text_hash,dimensions,vector,created_at)
                          VALUES (?,?,?,?,?,?,?)""", (job["lut_id"], self.embedding.fingerprint, current,
                          hashlib.sha256(text.encode()).hexdigest(), len(vector), vector.astype('<f4').tobytes(), now()))
            db.execute("UPDATE lut_index_jobs SET status='ready',stage='ready',error=NULL,updated_at=? WHERE id=?", (now(), job["id"]))

    def finish(self, job, status, error=None, stage="analysis"):
        with self.s.db.connect(write=True) as db:
            current = db.execute("SELECT revision FROM lut_profiles WHERE lut_id=?", (job["lut_id"],)).fetchone()[0]
            db.execute("UPDATE lut_index_jobs SET status=?,stage=?,error=?,updated_at=? WHERE id=?",
                       (status if current == job["revision"] else "stale", stage, error, now(), job["id"]))
