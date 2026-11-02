"""Synthetic local retrieval scale test; no provider calls and no user data writes."""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import time
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.config import Settings
from app.db import dump, now
from app.library_schemas import Metadata, SearchIntent
from app.lut_metadata import search_text
from app.service import Service


def measure(count):
    with tempfile.TemporaryDirectory(prefix='lut-scale-') as directory:
        root = Path(directory)
        settings = Settings(root, 'benchmark-only', embedding_provider='compatible',
                            embedding_url='https://unused.invalid/embeddings', embedding_model='synthetic-1024')
        service = Service(settings)
        try:
            rng = np.random.default_rng(42)
            matrix = rng.normal(size=(count,1024)).astype(np.float32)
            matrix /= np.linalg.norm(matrix,axis=1,keepdims=True)
            service.embeddings.embed_query = lambda text: matrix[0]
            cube = ('LUT_3D_SIZE 13\n' + ''.join(
                f'{r/12:.6f} {g/12:.6f} {b/12:.6f}\n' for b in range(13) for g in range(13) for r in range(13))).encode()
            started = time.perf_counter()
            with service.db.connect(write=True) as db:
                for i in range(count):
                    lid, name = f'synthetic-{i}', f'测试风格 {i}'
                    data = cube + f'# unique {i}\n'.encode()
                    ref = f'{lid}.cube'; (root/ref).write_bytes(data)
                    meta = Metadata(description='柔和低饱和冷调' if i%2 else '暖调复古高对比',
                                    input_space='srgb',output_space='srgb',compatibility_basis='合成基准数据').model_dump()
                    db.execute('INSERT INTO luts VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                               (lid,'benchmark',name,ref,ref,hashlib.sha256(data).hexdigest(),13,'srgb','srgb',len(data),now()))
                    db.execute('INSERT INTO lut_profiles(lut_id,compatibility,metadata_json,updated_at) VALUES (?,?,?,?)',
                               (lid,'confirmed',dump(meta),now()))
                    db.execute('INSERT INTO lut_embeddings VALUES (?,?,?,?,?,?,?)',
                               (lid,service.embeddings.fingerprint,0,hashlib.sha256(search_text(name,meta).encode()).hexdigest(),
                                1024,matrix[i].astype('<f4').tobytes(),now()))
            seed_ms=(time.perf_counter()-started)*1000
            timings=[]
            for _ in range(11):
                started=time.perf_counter()
                result=service.search.search('benchmark',SearchIntent(query='柔和低饱和但不要偏黄'))
                assert result['mode']=='hybrid' and result['candidates']
                timings.append((time.perf_counter()-started)*1000)
            rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return {'count':count,'dimensions':1024,'seed_files_metadata_vectors_ms':round(seed_ms,2),
                    'cold_ms':round(timings[0],2),'warm_p50_ms':round(float(np.percentile(timings[1:],50)),2),
                    'warm_p95_ms':round(float(np.percentile(timings[1:],95)),2),
                    'peak_rss_mib':round(rss/(1024**2 if sys.platform=='darwin' else 1024),2)}
        finally:
            service.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--count',type=int,choices=[1000,10000])
    args=parser.parse_args()
    if args.count:
        print(json.dumps(measure(args.count)))
    else:
        rows=[json.loads(subprocess.check_output([sys.executable,__file__,'--count',str(n)],text=True)) for n in (1000,10000)]
        report={'kind':'synthetic_local_retrieval','runs':rows,
                'note':'包含文件完整性检查、SQLite 读取、文本匹配、向量计算、融合和快照写入；固定查询向量，不包含远程 Embedding、模型规划、真实导入分析/索引重建或网页渲染。峰值 RSS 包含合成数据构建。'}
        path=ROOT/'data/qa/plan4/search-scale.json'; path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(report,ensure_ascii=False,indent=2))
