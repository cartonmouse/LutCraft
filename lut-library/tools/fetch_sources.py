"""Download the initial LUT source files without changing their contents."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import hashlib
import json
import os
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
IW = "https://luts.iwltbap.com/free/"
SOURCES = {
    "iwltbap-aspen.zip": IW + "IWLTBAP_-_Aspen_%28Free_LUT%29.zip",
    "iwltbap-sedona.zip": IW + "IWLTBAP_-_Sedona_%28Free_LUT%29.zip",
    "iwltbap-renata.zip": IW + "IWLTBAP_-_Renata_%28Free_LUT%29.zip",
    "iwltbap-humble.zip": IW + "IWLTBAP_-_Humble_%28Free_LUT%29.zip",
    "iwltbap-coronado.zip": IW + "IWLTBAP_Coronado_%28Free_LUT%29.zip",
    "iwltbap-blade-runner-2049.zip": IW + "IWLTBAP_-_Blade_Runner_2049_%28Free_LUT%29.zip",
    "iwltbap-kodachrome.zip": IW + "IWLTBAP_Kodachrome_-_Free_LUTs_%28Special_10K_Facebook_Fans%29.zip",
    "xmosaique-warm-instant.cube": "https://xmosaique.com/assets/luts/Warm%20Instant.cube",
    "xmosaique-dusty-slide.cube": "https://xmosaique.com/assets/luts/Dusty%20Slide.cube",
    "xmosaique-silver-mono.cube": "https://xmosaique.com/assets/luts/Silver%20Mono.cube",
    "xmosaique-infrared-mono.cube": "https://xmosaique.com/assets/luts/Infrared%20Mono.cube",
    "xmosaique-THIRD-PARTY-NOTICES.txt": "https://xmosaique.com/assets/luts/THIRD-PARTY-NOTICES.txt",
}


def fetch(item):
    name, url = item
    target = ROOT / "_sources" / name
    if not target.exists():
        fd, temp = tempfile.mkstemp(prefix=".download-", suffix=".part", dir=target.parent)
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with os.fdopen(fd, "wb") as output, urllib.request.urlopen(request, timeout=45) as response:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            if name.endswith(".zip"):
                with zipfile.ZipFile(temp) as archive:
                    if archive.testzip() is not None:
                        raise ValueError("ZIP integrity check failed: " + name)
            elif name.endswith(".cube"):
                if "LUT_3D_SIZE" not in Path(temp).read_text():
                    raise ValueError("Not a 3D CUBE file: " + name)
            os.replace(temp, target)
        except BaseException:
            Path(temp).unlink(missing_ok=True)
            raise
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    return {"filename": name, "download_url": url, "bytes": target.stat().st_size, "sha256": digest}


def main():
    (ROOT / "_sources").mkdir(parents=True, exist_ok=True)
    results = []
    errors = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch, item): item[0] for item in SOURCES.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
                results.append(result)
                print(f"OK {name}: {result['bytes']:,} bytes", flush=True)
            except Exception as exc:
                errors.append({"filename": name, "error": str(exc)})
                print(f"ERROR {name}: {exc}", flush=True)
    report = {"sources": sorted(results, key=lambda x: x["filename"]), "errors": errors}
    (ROOT / "source-downloads.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
