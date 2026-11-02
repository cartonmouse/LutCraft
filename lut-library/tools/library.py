"""List, index and verify CUBE, derived CLF, and explicit native Hald transforms.

Hald inspection uses numpy/pyvips. Paths are relative to the library root.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import shlex
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]


def inspect_transform(path):
    if path.suffix.lower() == ".cube":
        return inspect_cube(path)
    if path.suffix.lower() == ".clf":
        sys.path.insert(0, str(ROOT.parent / "backend"))
        from app.clf import inspect_clf
        return inspect_clf(path.read_bytes())
    if path.suffix.lower() == ".png":
        sys.path.insert(0, str(ROOT.parent / "backend"))
        from app.hald import inspect_hald
        return inspect_hald(path.read_bytes())
    raise ValueError("Unsupported runtime transform: " + str(path))


def inspect_cube(path):
    size = None
    title = ""
    domain_min = [0.0, 0.0, 0.0]
    domain_max = [1.0, 1.0, 1.0]
    count = 0
    low, high = math.inf, -math.inf
    numeric = hashlib.sha256()
    with path.open(encoding="utf-8-sig") as source:
        for number, raw in enumerate(source, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("TITLE"):
                parts = shlex.split(line, comments=True)
                title = " ".join(parts[1:])
                continue
            parts = line.split("#", 1)[0].split()
            key = parts[0]
            if key == "LUT_3D_SIZE":
                if size is not None or len(parts) != 2:
                    raise ValueError(f"{path}:{number}: duplicate/invalid LUT_3D_SIZE")
                size = int(parts[1])
                if not 2 <= size <= 256:
                    raise ValueError(f"{path}:{number}: unsupported LUT size")
            elif key in ("DOMAIN_MIN", "DOMAIN_MAX"):
                value = [float(x) for x in parts[1:]]
                if len(value) != 3 or not all(math.isfinite(x) for x in value):
                    raise ValueError(f"{path}:{number}: invalid domain")
                if key == "DOMAIN_MIN":
                    domain_min = value
                else:
                    domain_max = value
            else:
                try:
                    values = [float(x) for x in parts]
                except ValueError as exc:
                    raise ValueError(f"{path}:{number}: unsupported directive or invalid row") from exc
                if len(values) != 3 or not all(math.isfinite(x) for x in values):
                    raise ValueError(f"{path}:{number}: invalid RGB values")
                count += 1
                low = min(low, *values)
                high = max(high, *values)
                numeric.update(struct.pack(">3d", *values))
    if size is None or count != size ** 3:
        raise ValueError(f"{path}: data row count {count} does not match grid {size}")
    if any(a >= b for a, b in zip(domain_min, domain_max)):
        raise ValueError(f"{path}: invalid input domain")
    numeric.update(struct.pack(">I6d", size, *domain_min, *domain_max))
    return {
        "title": title,
        "lut_type": "3D",
        "grid_size": size,
        "data_rows": count,
        "domain_min": domain_min,
        "domain_max": domain_max,
        "output_value_range": [low, high],
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "mapping_sha256": numeric.hexdigest(),
    }


def scan():
    items, identifiers, mappings = [], set(), {}
    for metadata_path in sorted((ROOT / "luts").rglob("metadata.json")):
        metadata = json.loads(metadata_path.read_text())
        for field in ("id", "name", "filename", "category", "style_zh", "source_page", "input_profile", "license"):
            if not metadata.get(field):
                raise ValueError(f"{metadata_path}: missing {field}")
        if metadata["id"] in identifiers:
            raise ValueError("Duplicate ID: " + metadata["id"])
        identifiers.add(metadata["id"])
        path = (metadata_path.parent / metadata["filename"]).resolve()
        if not path.is_relative_to((ROOT / "luts").resolve()) or path.suffix.lower() not in (".cube", ".clf", ".png"):
            raise ValueError("LUT path must remain inside luts/ with a supported format")
        if path.suffix.lower() == ".png" and (metadata.get("format") != "HaldCLUT" or metadata.get("input_space") != "srgb" or metadata.get("output_space") != "srgb"):
            raise ValueError("PNG runtime entries must be explicitly classified sRGB HaldCLUTs")
        if path.suffix.lower() == ".clf" and not metadata.get("derived"):
            raise ValueError("A CLF must be explicitly marked as a derivative")
        technical = inspect_transform(path)
        key = technical["mapping_sha256"]
        if key in mappings:
            raise ValueError(f"Duplicate mapping: {metadata['id']} and {mappings[key]}")
        mappings[key] = metadata["id"]
        if metadata.get("original_sha256") and metadata["original_sha256"] != technical["sha256"]:
            raise ValueError(f"Original file checksum mismatch: {path}")
        items.append({**metadata, "path": path.relative_to(ROOT).as_posix(),
                      "metadata_path": metadata_path.relative_to(ROOT).as_posix(),
                      "technical": technical})
    if not items:
        raise ValueError("No LUTs found")
    return sorted(items, key=lambda x: x["id"])


def rebuild(items):
    catalog = {"schema_version": 1, "library_name": "Photo LUT Library", "count": len(items), "items": items}
    (ROOT / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
    lines = ["# LUT 目录", "", f"共 {len(items)} 款。由 `python3 tools/library.py reindex` 生成。", "",
             "| 名称 | 风格 | 网格 | 文件 | 来源 / 示例 | 入库 |", "|---|---|---|---|---|---|"]
    for item in items:
        lines.append(f"| {item['name']} | {item['style_zh']} | {item['technical']['grid_size']}³ | "
                     f"[{Path(item['path']).suffix[1:].upper()}]({item['path']}) | [来源]({item['source_page']}) | {item.get('batch', '')} |")
    lines += ["", "每款的输入要求、来源链接、授权记录、文件校验值详见同目录 metadata.json 和 catalog.json。", ""]
    (ROOT / "CATALOG.md").write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("list", "verify", "reindex"))
    args = parser.parse_args()
    items = scan()
    if args.command == "reindex":
        rebuild(items)
    elif args.command == "verify":
        saved = json.loads((ROOT / "catalog.json").read_text())
        if saved["items"] != items or saved["count"] != len(items):
            raise SystemExit("Catalog differs from files/metadata; inspect changes before reindexing.")
    else:
        for item in items:
            print(f"{item['id']}: {item['style_zh']} — {item['path']}")
    print(f"OK: {len(items)} valid LUTs with unique IDs and mappings.")


if __name__ == "__main__":
    main()
