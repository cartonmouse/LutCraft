"""Explicitly configured embedding endpoint, independent from the chat provider."""
import hashlib
import json
import numpy as np
import httpx
from .errors import AppError


class Embeddings:
    def __init__(self, settings):
        self.settings = settings

    @property
    def configured(self):
        s = self.settings
        return s.embedding_provider == "compatible" and bool(s.embedding_url and s.embedding_model)

    @property
    def fingerprint(self):
        s = self.settings
        return hashlib.sha256(json.dumps([
            s.embedding_provider, s.embedding_url, s.embedding_model, s.embedding_version,
            s.embedding_dimensions, s.embedding_send_dimensions, s.embedding_query_prefix, s.embedding_document_prefix,
        ], ensure_ascii=False).encode()).hexdigest()

    @staticmethod
    def normalize(values, count, dimensions):
        try:
            matrix = np.asarray(values, dtype=np.float32)
            if matrix.shape != (count, dimensions) or not np.isfinite(matrix).all():
                raise ValueError()
            norms = np.linalg.norm(matrix.astype(np.float64), axis=1, keepdims=True)
            if (norms < 1e-12).any():
                raise ValueError()
            return (matrix / norms).astype(np.float32)
        except (ValueError, TypeError, OverflowError) as exc:
            raise AppError("embedding_format", "向量服务返回了无效的维度或数值。", 502) from exc

    def _embed(self, texts, prefix):
        if not self.configured:
            raise AppError("embedding_unconfigured", "Embedding 尚未配置，当前使用关键词检索。", 503)
        s = self.settings
        batches = []
        try:
            with httpx.Client(timeout=s.embedding_timeout, follow_redirects=False) as client:
                for offset in range(0, len(texts), s.embedding_batch_size):
                    batch = texts[offset:offset + s.embedding_batch_size]
                    payload = {"model": s.embedding_model, "input": [prefix + t for t in batch],
                               "encoding_format": "float"}
                    if s.embedding_send_dimensions:
                        payload["dimensions"] = s.embedding_dimensions
                    response = client.post(s.embedding_url,
                        headers={"Authorization": f"Bearer {s.embedding_key}"} if s.embedding_key else {},
                        json=payload)
                    if response.status_code != 200:
                        raise AppError("embedding_http", f"向量服务返回 HTTP {response.status_code}，当前使用关键词检索。", 502)
                    rows = response.json()["data"]
                    if sorted(r["index"] for r in rows) != list(range(len(batch))):
                        raise ValueError()
                    rows = sorted(rows, key=lambda r: r["index"])
                    batches.append(self.normalize([r["embedding"] for r in rows], len(batch), s.embedding_dimensions))
        except httpx.HTTPError as exc:
            raise AppError("embedding_network", "向量服务暂时无法连接，当前使用关键词检索。", 503) from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise AppError("embedding_format", "向量服务响应格式无效。", 502) from exc
        return np.concatenate(batches) if batches else np.empty((0, s.embedding_dimensions), dtype=np.float32)

    def embed_documents(self, texts):
        return self._embed(texts, self.settings.embedding_document_prefix)

    def embed_query(self, text):
        return self._embed([text], self.settings.embedding_query_prefix)[0]
