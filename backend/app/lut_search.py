"""Owned hybrid retrieval with explicit constraints and versioned candidate snapshots."""
import hashlib
import json
import re
import threading
import time
import numpy as np
from .db import dump, now, uid, unpack
from .errors import AppError
from .lut_metadata import search_text

GROUPS = {
    "低饱和": ["低饱和", "淡雅", "颜色淡", "色彩淡", "清淡"],
    "清新": ["清新", "日系", "日式", "通透", "轻盈", "淡雅"],
    "柔和": ["柔和", "低对比", "柔美", "自然柔光", "soft"],
    "暖色": ["暖色", "暖调", "偏暖", "温暖", "warm", "金色"],
    "冷色": ["冷色", "冷调", "偏冷", "清冷", "cool", "蓝调"],
    "复古": ["复古", "胶片", "film", "怀旧", "褪色"],
    "黑白": ["黑白", "单色", "monochrome", "mono"],
    "鲜艳": ["鲜艳", "高饱和", "浓郁"],
    "偏黄": ["偏黄", "发黄", "黄色", "太黄", "泛黄", "黄调"],
    "褪色": ["褪色", "发灰", "灰蒙", "灰感"],
    "明亮": ["明亮", "透亮", "亮丽"],
    "高对比": ["高对比", "硬朗", "强烈"],
}


def concepts(text):
    text = text.casefold()
    return {key for key, aliases in GROUPS.items() if any(a in text for a in aliases)}


def tokens(text):
    result = set(re.findall(r"[a-z0-9]+", text.casefold()))
    for word in re.findall(r"[\u4e00-\u9fff]+", text):
        result.update(word[i:i+2] for i in range(len(word)-1))
    return result - {"风格", "效果", "照片", "调成", "一个", "想要", "需要", "使用", "选择", "推荐"}


def intent_terms(req):
    avoided, excluded = set(), set()
    query = req.query
    for match in list(re.finditer(r"(?:不要|别|避免|不能|不想要|不需要)([^，。；,;！!]+)", query)):
        negative = concepts(match.group(1))
        avoided |= negative
        if "黑白" in negative:
            excluded.add("黑白")
        query = query.replace(match.group(0), " ")
    avoided |= concepts(" ".join(req.avoid_features))
    excluded |= concepts(" ".join(req.excluded_features))
    # Literal exclusions work for custom tags as well as the built-in vocabulary.
    excluded |= set(req.excluded_features)
    positive = query + " " + " ".join(req.desired_features)
    return positive, avoided, excluded


class LutSearch:
    def __init__(self, service, embedding):
        self.s, self.embedding = service, embedding
        self.cache_key = None
        self.cache_matrix = None
        self.cache_lock = threading.Lock()
        self.file_cache = {}

    def file_ok(self, row):
        path = self.s.path(row["file_ref"])
        try:
            stat = path.stat()
            key = (row["id"], row["sha256"], stat.st_size, stat.st_mtime_ns)
            with self.cache_lock:
                if key in self.file_cache:
                    return self.file_cache[key]
            good = stat.st_size == row["byte_size"] and hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
            with self.cache_lock:
                if len(self.file_cache) > 20000:
                    self.file_cache.clear()
                self.file_cache[key] = good
            return good
        except OSError:
            return False

    def context_key(self, db, pid, owner):
        if not pid:
            return None
        p = self.s.project(db, pid, owner)
        assets = [tuple(r) for r in db.execute("SELECT id,revision FROM assets WHERE project_id=? ORDER BY ordinal", (pid,))]
        return hashlib.sha256(dump([p["selected"], p["viewed"], p["preferences"], assets]).encode()).hexdigest()

    def search(self, owner, req, pid=None):
        pid = pid or None
        started = time.monotonic()
        with self.s.db.connect() as db:
            context_key = self.context_key(db, pid, owner)
            revision = self.s.project(db, pid, owner)["revision"] if pid else None
            rows = [unpack(r) for r in db.execute("""SELECT l.*,p.revision,p.metadata_json,p.evidence_json,p.analysis_json
                FROM luts l JOIN lut_profiles p ON l.id=p.lut_id
                WHERE l.owner=? AND p.enabled=1 AND p.compatibility='confirmed' ORDER BY l.id""", (owner,))]
            vectors = {r["lut_id"]: dict(r) for r in db.execute("""SELECT e.* FROM lut_embeddings e JOIN luts l ON l.id=e.lut_id
                       WHERE l.owner=? AND e.fingerprint=?""", (owner, self.embedding.fingerprint))}
        rows = [r for r in rows if r["metadata"]["input_space"] == r["metadata"]["output_space"] == "srgb" and self.file_ok(r)]
        positive, avoided, excluded = intent_terms(req)
        desired = concepts(positive)
        if "清新" in desired:
            desired |= {"低饱和", "柔和", "明亮"}
        query_tokens = tokens(positive)
        results = {}
        unsupported = bool(re.search(r"换背景|去路人|去除路人|磨皮|瘦脸|加颗粒|添加颗粒|抠图", req.query))
        for row in rows:
            meta = row["metadata"]
            text = search_text(row["name"], meta, row["analysis"])
            measured = row["analysis"].get("tags", [])
            available = concepts(text + " " + " ".join(measured))
            if excluded & (available | set(meta["tags"]) | set(measured)):
                continue
            exact = bool(req.exact_name and req.exact_name.casefold() in [x.casefold() for x in [row["name"], *meta["aliases"]]])
            if req.exact_name and not exact:
                continue
            overlap = desired & available
            described = desired & concepts(search_text(row["name"], meta))
            literal = query_tokens & tokens(text)
            # A complete name match remains useful for short English and Chinese IDs.
            named = row["name"].casefold() in positive.casefold()
            lexical = 10 * exact + 8 * named + 2 * len(described) + .5 * len(overlap - described) + min(len(literal), 5) * .35
            conflicts = sorted(avoided & available)
            if "清新" in desired:
                if "高对比" in available:
                    conflicts.append("高对比可能偏离柔和方向")
                if "黑白" in available:
                    conflicts.append("黑白风格需确认")
            if re.search(r"肤色.*自然|自然.*肤色|保留肤色|肤色不变", req.query) and not any(
                phrase in " ".join(meta["use_cases"]) for phrase in ("自然肤色", "肤色自然", "保留肤色")
            ):
                conflicts.append("自然肤色表现尚未验证")
            reasons = (["名称精确匹配"] if exact or named else []) + [f"相关特征：{t}" for t in sorted(overlap)]
            if literal and not reasons:
                reasons.append("描述或标签包含：" + "、".join(sorted(literal)[:4]))
            results[row["id"]] = {"row": row, "lexical": lexical, "reasons": reasons, "conflicts": conflicts, "semantic": None}
        mode = "keyword_fallback"
        degradation = None if self.embedding.configured else "Embedding 尚未配置，当前使用关键词和同义词检索。"
        if self.embedding.configured and results and not req.exact_name and not unsupported:
            valid = [r for r in rows if r["id"] in results and r["id"] in vectors and vectors[r["id"]]["revision"] == r["revision"]
                     and vectors[r["id"]]["text_hash"] == hashlib.sha256(search_text(r["name"], r["metadata"], r["analysis"]).encode()).hexdigest()]
            if valid:
                try:
                    query = self.embedding.embed_query(positive.strip() or req.query)
                    key = tuple((r["id"], r["revision"], vectors[r["id"]]["created_at"], self.embedding.fingerprint) for r in valid)
                    with self.cache_lock:
                        if self.cache_key != key:
                            values = [np.frombuffer(vectors[r["id"]]["vector"], dtype='<f4') for r in valid]
                            self.cache_matrix = self.embedding.normalize(values, len(valid), self.s.settings.embedding_dimensions)
                            self.cache_key = key
                        matrix = self.cache_matrix
                    scores = matrix @ query
                    for r, score in zip(valid, scores):
                        results[r["id"]]["semantic"] = float(score)
                    mode, degradation = "hybrid", None
                    if len(valid) < len(results):
                        degradation = "部分 LUT 尚未建立当前版本向量，已同时使用关键词检索。"
                except (AppError, ValueError) as exc:
                    degradation = exc.message if isinstance(exc, AppError) else "向量索引无效，当前使用关键词检索。"
            else:
                degradation = "当前库尚无可用向量，请在 LUT 管理中执行分析与建索引。"
        ranked = {}
        lexical = sorted((k for k,v in results.items() if v["lexical"] > 0), key=lambda k: (-results[k]["lexical"], results[k]["row"]["name"], k))[:20]
        semantic = sorted((k for k,v in results.items() if v["semantic"] is not None), key=lambda k: (-results[k]["semantic"], results[k]["row"]["name"], k))[:20]
        for sequence in (lexical, semantic):
            for rank, key in enumerate(sequence):
                ranked[key] = ranked.get(key, 0) + 1 / (60 + rank + 1)
        threshold = self.s.settings.embedding_min_similarity
        for key in list(ranked):
            item = results[key]
            if item["lexical"] == 0 and threshold is not None and item["semantic"] < threshold:
                ranked.pop(key)
            else:
                ranked[key] *= 0.35 ** len(item["conflicts"])
                accepted = sum(1 for field in ("description", "tags")
                               if item["row"]["evidence"].get(field, {}).get("review") == "accepted")
                ranked[key] *= 1 + .01 * accepted
        candidates = []
        if not unsupported:
            for key in sorted(ranked, key=lambda k: (-ranked[k], results[k]["row"]["name"], k))[:req.limit]:
                item = results[key]
                r, meta = item["row"], item["row"]["metadata"]
                candidates.append({"id": key, "name": r["name"], "revision": r["revision"],
                    "description": (meta["description"] or r["analysis"].get("description", ""))[:600], "tags": meta["tags"],
                    "reasons": item["reasons"] or ["描述语义接近，需检查实际效果"],
                    "conflicts": item["conflicts"], "evidence": {k: v for k,v in r["evidence"].items() if k in ("description", "tags", "compatibility")},
                    "recommended_strength": meta["recommended_strength"], "strength_basis": meta["strength_basis"],
                    "trial_strength": .75, "requires_review": bool(item["conflicts"] or (item["lexical"] == 0 and threshold is None))})
        ambiguous_name = bool(req.exact_name and len(results) > 1)
        if ambiguous_name:
            for candidate in candidates:
                candidate["requires_review"] = True
                candidate["conflicts"].append("多个 LUT 使用相同名称或别名，请选择具体版本")
        status = "no_match" if not candidates else "needs_clarification" if candidates[0]["requires_review"] else "ok"
        result = {"search_id": uid(), "status": status, "mode": mode, "message": degradation,
                  "query": req.query, "candidates": candidates,
                  "elapsed_ms": round((time.monotonic() - started) * 1000, 1)}
        if unsupported:
            result["message"] = "该需求包含 LUT 无法执行的编辑，请使用相应修图功能。"
        elif ambiguous_name:
            result["message"] = "找到多个同名 LUT，请根据来源与描述选择具体版本。"
        elif not candidates:
            result["message"] = (degradation + " " if degradation else "") + "当前可用库中没有足够匹配的 LUT。"
        with self.s.db.connect(write=True) as db:
            if context_key != self.context_key(db, pid, owner):
                raise AppError("search_stale", "检索期间照片或偏好发生变化，请重试。", 409)
            db.execute("INSERT INTO lut_search_runs(id,owner,project_id,project_revision,result_json,created_at,expires_at) VALUES (?,?,?,?,?,?,?)",
                       (result["search_id"], owner, pid, revision, dump({**result, "_context": context_key}), now(), time.time() + 3600))
            db.execute("DELETE FROM lut_search_runs WHERE owner=? AND expires_at<?", (owner, time.time()))
        return result

    def carry_after_memory(self, db, owner, pid, search_id):
        row = db.execute("SELECT result_json FROM lut_search_runs WHERE id=? AND owner=? AND project_id=?",
                         (search_id, owner, pid)).fetchone()
        result = json.loads(row[0])
        result["_context"] = self.context_key(db, pid, owner)
        db.execute("UPDATE lut_search_runs SET result_json=? WHERE id=?", (dump(result), search_id))

    def latest(self, owner, pid, db=None):
        if db is None:
            with self.s.db.connect() as conn:
                return self.latest(owner, pid, conn)
        row = db.execute("SELECT result_json FROM lut_search_runs WHERE owner=? AND project_id=? AND expires_at>? ORDER BY created_at DESC LIMIT 1", (owner, pid, time.time())).fetchone()
        if not row:
            return None
        result = json.loads(row[0])
        if result.pop("_context") != self.context_key(db, pid, owner):
            return None
        return result

    def validate(self, owner, pid, search_id, lid, db=None):
        if db is None:
            with self.s.db.connect() as conn:
                return self.validate(owner, pid, search_id, lid, conn)
        row = unpack(db.execute("SELECT * FROM lut_search_runs WHERE id=? AND owner=? AND project_id=? AND expires_at>?", (search_id, owner, pid, time.time())).fetchone())
        if not row or row["result"]["_context"] != self.context_key(db, pid, owner):
            raise AppError("search_stale", "候选已过期或工作区已变化，请重新检索。", 409)
        candidate = next((r for r in row["result"]["candidates"] if r["id"] == lid), None)
        profile = self.s.metadata.get(owner, lid, db)
        if not candidate or candidate["revision"] != profile["revision"] or not profile["enabled"] or profile["compatibility"] != "confirmed":
            raise AppError("candidate_invalid", "LUT 不属于有效候选，或元信息已变化，请重新检索。", 409)
        return candidate
