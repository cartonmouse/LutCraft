"""Render review-only sample/LUT matches at 100% through the production engine."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pyvips
from backend.app.imaging import render, inspect
from backend.app.single_pass import catalog, load_catalog_processor


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(plan_path, output):
    plan = json.loads(plan_path.read_text())
    rows = {r['id']: r for r in catalog()}
    output.mkdir(parents=True, exist_ok=True)
    items = []
    for n, match in enumerate(plan['items'], 1):
        row = rows[match['lut_id']]
        source = (ROOT / match['source']).resolve()
        if not source.is_relative_to(ROOT) or digest(source) != match['source_sha256']:
            raise ValueError('Sample source path or checksum mismatch')
        recipe = {'lut': {'id': row['id'], 'name': row['name'], 'sha256': row['sha256'], 'strength': 1.0}}
        original = output / f'{n:02d}-original.png'
        result = output / f'{n:02d}-{row["id"]}-100.png'
        render(source, original, {}, max_edge=960)
        render(source, result, recipe, max_edge=960, lut_processor=load_catalog_processor(row))
        inspect(original)
        inspect(result)
        # A paired review image contains the supplied input and actual output.
        pair = output / f'{n:02d}-comparison.jpg'
        thumbs = [pyvips.Image.thumbnail(str(p), 300, height=450, size='down').gravity('centre', 300, 450, extend='background', background=[24,24,24]) for p in (original, result)]
        pyvips.Image.arrayjoin(thumbs, across=2, shim=8, background=[24,24,24]).jpegsave(str(pair), Q=94)
        items.append({**match, 'number': n, 'lut_name': row['name'], 'lut_sha256': row['sha256'],
                      'recipe': recipe, 'original': original.name, 'result': result.name,
                      'result_sha256': digest(result), 'comparison': pair.name})
        print(f'{n}/{len(plan["items"])} {row["name"]}: 100%', flush=True)
    manifest = {'status': 'review-only', 'strength': 1.0, 'additional_adjustments': False,
                'plan_sha256': digest(plan_path), 'runtime_count': len(rows), 'items': items}
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.plan, args.output)
