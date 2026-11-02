"""Inspect all rendered story assets and create grouped visual review sheets."""
import argparse
import hashlib
import json
from pathlib import Path
import textwrap
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]


def review(build_id, output):
    folder=ROOT/'data/style-gallery/builds'/build_id
    value=json.loads((folder/'manifest.json').read_text())
    output.mkdir(parents=True,exist_ok=True)
    rows=[r for r in value['items'] if r.get('story',{}).get('examples')]
    originals={s['id']:s['source_sha256'] for s in value['scenes']}
    font=ImageFont.truetype('/System/Library/Fonts/STHeiti Light.ttc',14)
    metrics=[]
    for start in range(0,len(rows),12):
        sheet=Image.new('RGB',(1440,1240),'#181818');draw=ImageDraw.Draw(sheet)
        for index,item in enumerate(rows[start:start+12]):
            x,y=index%3*480,index//3*310
            label=f'{start+index+1:03d} {item["label"]}'
            for line,text in enumerate(textwrap.wrap(label,46)[:2]):draw.text((x+5,y+2+line*18),text,font=font,fill='white')
            seen={originals[item['sample_id']]}
            for j,e in enumerate(item['story']['examples']):
                path=folder/'files'/e['image']
                assert hashlib.sha256(path.read_bytes()).hexdigest()==e['result_sha256']==value['assets'][e['image']]
                assert e['recipe']['lut']['id']==item['id'] and e['recipe']['lut']['strength']==1.0
                assert e['source_sha256'] not in seen
                seen.add(e['source_sha256'])
                im=Image.open(path).convert('RGB');im.thumbnail((150,240));sheet.paste(im,(x+j*160+(150-im.width)//2,y+42+(240-im.height)//2))
                a=np.array(im,dtype=float)/255;lum=a@np.array([.2126,.7152,.0722])
                record={'number':start+index+1,'lut_id':item['id'],'label':item['label'],'example':j+1,
                        'mean':round(float(lum.mean()),4),'black':round(float((lum<.025).mean()),4),'white':round(float((lum>.98).mean()),4)}
                metrics.append(record)
                if record['black']>.25 or record['white']>.2 or record['mean']<.12:
                    draw.text((x+j*160+5,y+287),'CHECK',font=font,fill='#ffd768')
        sheet.save(output/f'review-{start//12+1:02d}.jpg',quality=93)
    (output/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2))
    print(json.dumps({'luts':len(rows),'images':len(metrics),'sheets':(len(rows)+11)//12,'flagged':[r for r in metrics if r['black']>.25 or r['white']>.2 or r['mean']<.12]},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('build_id');parser.add_argument('output',type=Path)
    args=parser.parse_args();review(args.build_id,args.output)
