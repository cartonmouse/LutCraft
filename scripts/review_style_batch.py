"""Create numbered contact sheets for visual review of actual 100% renders."""
import argparse
import json
from pathlib import Path
import textwrap
from PIL import Image, ImageDraw, ImageFont


def sheets(folder):
    folder = Path(folder)
    items = json.loads((folder/'manifest.json').read_text())['items']
    font = ImageFont.load_default(size=14)
    for start in range(0, len(items), 12):
        sheet = Image.new('RGB', (1344, 1440), '#181818')
        draw = ImageDraw.Draw(sheet)
        for index, item in enumerate(items[start:start+12]):
            x, y = index % 3 * 448, index // 3 * 360
            label = f'{item["number"]:03d}  '+item['lut_name'].replace(' · 照片版', '')
            for line, text in enumerate(textwrap.wrap(label, 48)[:2]):
                draw.text((x+6,y+line*18+3),text,font=font,fill='white')
            for side, field in enumerate(('original','result')):
                im = Image.open(folder/item[field]).convert('RGB')
                im.thumbnail((218, 310))
                sheet.paste(im,(x+side*224+(218-im.width)//2,y+42+(310-im.height)//2))
        target=folder/f'review-{start//12+1:02d}.jpg'
        sheet.save(target, quality=92)
        print(target)

if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('folder',type=Path)
    sheets(parser.parse_args().folder)
