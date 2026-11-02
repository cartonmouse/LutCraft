"""Import the curated first batch from official downloads; preserve source bytes."""
from pathlib import Path
import hashlib
import json
import shutil
import zipfile

from fetch_sources import ROOT, SOURCES
from library import inspect_cube, rebuild, scan

IW_PAGE = "https://blog.iwltbap.com/the-10-free-cinematic-luts-by-iwltbap/"
XM_PAGE = "https://xmosaique.com/luts/"
# ID, category, style, source file, exact original CUBE filename, tags
ITEMS = [
    ("iwltbap-aspen", "cinematic", "深青高对比", "iwltbap-aspen.zip", "IWLTBAP Aspen - Standard.cube", ["冷调", "青绿", "高对比"]),
    ("iwltbap-sedona", "cinematic", "暖调青橙", "iwltbap-sedona.zip", "IWLTBAP Sedona - Standard.cube", ["暖调", "青橙", "电影"]),
    ("iwltbap-renata", "dreamy", "深蓝浅绿、淡肤色", "iwltbap-renata.zip", "IWLTBAP Renata - Standard.cube", ["梦幻", "蓝色", "自然柔光"]),
    ("iwltbap-humble", "moody", "暖绿暗部", "iwltbap-humble.zip", "IWLTBAP Humble - Standard.cube", ["绿色", "雾景", "氛围"]),
    ("iwltbap-coronado", "night", "冷蓝夜景", "iwltbap-coronado.zip", "IWLTBAP Coronado - Standard.cube", ["冷调", "蓝色", "夜景"]),
    ("iwltbap-blade-runner-2049", "cinematic", "暗绿科幻", "iwltbap-blade-runner-2049.zip", "IWLTBAP Blade Runner 2049 - Standard.cube", ["科幻", "绿色", "暗调"]),
    ("iwltbap-k64", "film", "蓝与洋红复古", "iwltbap-kodachrome.zip", "IWLTBAP K64.cube", ["胶片", "复古", "洋红"]),
    ("xmosaique-warm-instant", "instant", "奶油暖黄拍立得", "xmosaique-warm-instant.cube", "Warm Instant.cube", ["暖调", "拍立得", "抬黑"]),
    ("xmosaique-dusty-slide", "film", "褪色淡紫幻灯片", "xmosaique-dusty-slide.cube", "Dusty Slide.cube", ["低饱和", "褪色", "淡紫"]),
    ("xmosaique-silver-mono", "black-and-white", "柔和中性黑白", "xmosaique-silver-mono.cube", "Silver Mono.cube", ["黑白", "中性", "柔和"]),
    ("xmosaique-infrared-mono", "black-and-white", "红外风格黑白", "xmosaique-infrared-mono.cube", "Infrared Mono.cube", ["黑白", "红外风格", "深色天空"]),
]


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != data:
        raise FileExistsError(f"Refusing to replace changed file: {path}")
    if not path.exists():
        path.write_bytes(data)


def main():
    # Keep old download links usable and make the new library self-contained.
    aspen = ROOT / "_sources" / "iwltbap-aspen.zip"
    previous = ROOT.parent / "downloads" / "IWLTBAP_Aspen_Official.zip"
    if not aspen.exists() and previous.exists():
        shutil.copyfile(previous, aspen)
    for uid, category, style, source_name, original_name, tags in ITEMS:
        source = ROOT / "_sources" / source_name
        docs = []
        member = None
        if source.suffix == ".zip":
            with zipfile.ZipFile(source) as archive:
                candidates = [n for n in archive.namelist() if Path(n).name == original_name and "__MACOSX" not in n and "/BONUS/" not in n]
                if len(candidates) != 1:
                    raise ValueError(f"Ambiguous/missing LUT: {source_name}: {candidates}")
                member = candidates[0]
                data = archive.read(member)
                for name in archive.namelist():
                    basename = Path(name).name
                    if "__MACOSX" not in name and basename.lower().endswith(".pdf") and "grading pack" in basename.lower():
                        doc = ROOT / "licenses" / uid / basename
                        put(doc, archive.read(name))
                        docs.append(doc.relative_to(ROOT).as_posix())
            publisher, page = "IWLTBAP", IW_PAGE
            license_info = {"id": "LicenseRef-IWLTBAP-Free", "status": "官方免费发布，具体条款见随包原作者说明", "documents": docs, "redistribution_verified": False}
            profile = "Standard / display-referred"
            if uid == "iwltbap-k64":
                profile = "Standard（原包不带 LOG 后缀的版本；Renata 包另附同名 LOG / V-Log 版本）"
        else:
            data = source.read_bytes()
            publisher, page = "xMosaique", XM_PAGE
            notice = ROOT / "licenses" / "xmosaique-THIRD-PARTY-NOTICES.txt"
            put(notice, (ROOT / "_sources" / "xmosaique-THIRD-PARTY-NOTICES.txt").read_bytes())
            license_info = {"id": "MIT", "status": "按发布方第三方声明保留 MIT 许可与版权说明", "documents": [notice.relative_to(ROOT).as_posix()], "upstream": "https://github.com/YahiaAngelo/Film-Luts"}
            profile = "Rec.709 / sRGB, display-referred（发布方注明）"
        destination = ROOT / "luts" / category / uid
        filename = uid + ".cube"
        put(destination / filename, data)
        inspect_cube(destination / filename)
        metadata = {
            "schema_version": 1, "id": uid,
            "name": original_name.removesuffix(".cube").removesuffix(" - Standard"),
            "publisher": publisher, "filename": filename, "category": category,
            "style_zh": style, "tags": tags, "input_profile": profile,
            "source_page": page, "preview_page": page,
            "download_url": SOURCES[source_name],
            "source_archive": source.relative_to(ROOT).as_posix(),
            "archive_member": member, "original_filename": original_name,
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "original_sha256": hashlib.sha256(data).hexdigest(),
            "added_date": "2026-10-28", "batch": "已有文件归档" if uid == "iwltbap-aspen" else "2026-10-28 新增",
            "license": license_info, "file_modified": False,
        }
        put(destination / "metadata.json", (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode())
        print(f"Imported {uid}")
    rebuild(scan())


if __name__ == "__main__":
    main()
