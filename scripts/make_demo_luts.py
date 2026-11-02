"""Generate our own sRGB test LUTs. These do not simulate a camera brand."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def cube(size=33, warm=True):
    name = f"Warm sRGB Demo {size}" if warm else f"Identity {size}"
    rows = [f'TITLE "{name}"', f'LUT_3D_SIZE {size}', 'DOMAIN_MIN 0 0 0', 'DOMAIN_MAX 1 1 1']
    for b in range(size):
        for g in range(size):
            for r in range(size):
                rgb = (r / (size - 1), g / (size - 1), b / (size - 1))
                if warm:
                    rgb = (rgb[0] * 1.02 + .02, rgb[1] * .99 + .01, rgb[2] * .92 + .012)
                rows.append(' '.join(f'{min(1, max(0, v)):.7f}' for v in rgb))
    return ('\n'.join(rows) + '\n').encode()


if __name__ == '__main__':
    folder = ROOT / 'data/test-fixtures'
    folder.mkdir(parents=True, exist_ok=True)
    for size in (33, 65):
        path = folder / f'warm-srgb-{size}.cube'
        path.write_bytes(cube(size))
        print(path)
