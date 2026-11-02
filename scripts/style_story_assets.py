"""Render configured detail stories through the same production LUT pipeline."""
import json
from pathlib import Path

from backend.app.imaging import render
from backend.app.single_pass import catalog, load_catalog_processor
from backend.app.style_gallery import digest

ROOT = Path(__file__).resolve().parents[1]
STORIES = ROOT / 'prototypes/lut-studio/style-stories.json'


def add_stories(value, files, config=STORIES):
    if not config.exists():
        return
    rows = {r['id']: r for r in catalog()}
    items = {r['id']: r for r in value['items']}
    stories = json.loads(config.read_text())['items']
    for number, story in enumerate(stories, 1):
        lut_id = story['lut_id']
        if lut_id not in items:
            continue
        item = items[lut_id]
        result = {k: story[k] for k in ('headline', 'description', 'traits')}
        result['examples'] = []
        if item.get('availability', 'ready') != 'ready':
            if story['examples']:
                raise ValueError('Unadapted LUT cannot have rendered examples')
            item['story'] = result
            continue
        row = rows[lut_id]
        examples = story['examples']
        if len(examples) != 3 or len({e['source_sha256'] for e in examples}) != 3:
            raise ValueError('Each story needs three distinct source photos')
        recipe = {'lut': {'id': lut_id, 'name': row['name'], 'sha256': row['sha256'], 'strength': 1.0}}
        processor = None
        previous = {e['image']: e for e in item.get('story', {}).get('examples', [])}
        for index, example in enumerate(examples, 1):
            source = (ROOT / example['source']).resolve()
            if not source.is_relative_to(ROOT) or digest(source) != example['source_sha256']:
                raise ValueError('Story source checksum/path mismatch')
            target = files / f'story-{lut_id}-{index}-100.png'
            if target.parent != files:
                raise ValueError('Invalid story asset path')
            old = previous.get(target.name, {})
            cached = (target.exists() and old.get('source_sha256') == example['source_sha256']
                      and old.get('recipe') == recipe and digest(target) == old.get('result_sha256'))
            if not cached:
                if processor is None:
                    processor = load_catalog_processor(row)
                render(source, target, recipe, max_edge=960, lut_processor=processor)
            value['assets'][target.name] = digest(target)
            result['examples'].append({**example, 'image': target.name,
                'recipe': recipe, 'result_sha256': value['assets'][target.name]})
        item['story'] = result
        if number % 25 == 0:
            print(f'Stories {number}/{len(stories)}', flush=True)
    value['story_config_sha256'] = digest(config)
    value['pipeline_sha256']['scripts/style_story_assets.py'] = digest(Path(__file__))
