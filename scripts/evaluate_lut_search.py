"""Run catalog-based retrieval checks in an isolated database; never edit user projects."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import tempfile
import time
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'data/qa/plan4/search-evaluation.json')
    parser.add_argument('--live-embedding', action='store_true')
    args = parser.parse_args()
    cases = json.loads((ROOT / 'lut-library/search-evaluation.json').read_text())
    catalog = json.loads((ROOT / 'lut-library/catalog.json').read_text())['items']
    with tempfile.TemporaryDirectory(prefix='lut-evaluation-') as directory:
        settings = Settings(Path(directory), 'evaluation-secret')
        if args.live_embedding:
            configured = Settings.load()
            for name in settings.__dataclass_fields__:
                if name.startswith('embedding_'):
                    setattr(settings, name, getattr(configured, name))
            if settings.embedding_provider == 'disabled' or not settings.embedding_url or not settings.embedding_model:
                raise SystemExit('请先配置独立 Embedding 服务；未执行真实向量验收。')
        results = []
        with TestClient(create_app(settings)) as c:
            ids = {}
            for entry in catalog:
                response = c.post('/api/luts', data={'color_space': 'srgb', 'name': entry['name']},
                                  files={'file': (entry['filename'], (ROOT/'lut-library'/entry['path']).read_bytes())})
                response.raise_for_status()
                ids[response.json()['id']] = entry['id']
            deadline = time.monotonic() + 180
            while True:
                profiles = c.get('/api/luts').json()
                if all(r['profile']['job']['status'] not in ('queued','running') for r in profiles):
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError('Index jobs timed out')
                time.sleep(.1)
            index_results = [{
                'id': ids[r['id']], 'index_status': r['profile']['index_status'],
                'job_status': r['profile']['job']['status'], 'stage': r['profile']['job']['stage'],
                'error': r['profile']['job'].get('error'),
            } for r in profiles]
            if args.live_embedding and any(r['index_status'] != 'ready' for r in index_results):
                raise SystemExit('真实向量验收未通过：部分 LUT 索引未就绪。' + json.dumps(index_results,ensure_ascii=False))
            for case in cases['cases']:
                response = c.post('/api/luts/search', json={'query': case['query'], 'exact_name': case.get('exact_name')})
                response.raise_for_status()
                found = response.json()
                actual = [ids[r['id']] for r in found['candidates']]
                hit = bool(set(actual[:3]) & set(case['relevant'])) if case['relevant'] else not actual
                results.append({**case, 'actual': actual, 'status': found['status'], 'mode': found['mode'],
                                'message':found['message'],
                                'hit': hit, 'constraint_ok': not (set(actual) & set(case.get('exclude', []))),
                                'elapsed_ms': found['elapsed_ms']})
    positive = [r for r in results if r['relevant']]
    negative = [r for r in results if not r['relevant']]
    rng = np.random.default_rng(20261028)
    scales = []
    for count in (1000, 10000):
        matrix = rng.normal(size=(count,1024)).astype(np.float32)
        matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
        query = matrix[0]
        timings = []
        for _ in range(30):
            started = time.perf_counter()
            scores = matrix @ query
            np.argpartition(scores, -5)[-5:]
            timings.append((time.perf_counter()-started)*1000)
        scales.append({'count':count,'dimensions':1024,'matrix_bytes':matrix.nbytes,
                       'p50_ms':float(np.percentile(timings,50)),'p95_ms':float(np.percentile(timings,95))})
    report = {'label_status':cases['status'],'live_embedding':args.live_embedding,
              'embedding_model':settings.embedding_model if args.live_embedding else None,
              'embedding_dimensions':settings.embedding_dimensions if args.live_embedding else None,
              'indexes':index_results, 'retrieval_modes':dict(Counter(r['mode'] for r in results)),
              'hit_at_3':sum(r['hit'] for r in positive)/len(positive),
              'negative_accuracy':sum(r['hit'] for r in negative)/len(negative),
              'constraint_violations':sum(not r['constraint_ok'] for r in results),
              'cases':results, 'synthetic_vector_only_benchmark':scales,
              'benchmark_note':'仅向量计算；不包含文件校验、数据库读取、网络请求或端到端延迟。'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('live_embedding','embedding_model','retrieval_modes','hit_at_3','negative_accuracy','constraint_violations')},ensure_ascii=False))
    print(args.output)


if __name__ == '__main__':
    main()
