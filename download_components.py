"""Download every Google Drive asset listed in ComponentLinks.csv.

The audit file makes retries safe: each source URL receives a unique local name
and is recorded together with the final HTTP response details.
"""

from __future__ import annotations

import csv
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener


ROOT = Path(__file__).resolve().parent
LINKS_PATH = ROOT / "ComponentLinks.csv"
COMPONENTS_DIR = ROOT / "components"
AUDIT_PATH = COMPONENTS_DIR / "download-audit.csv"


def file_id_from_url(url: str) -> str:
    file_id = parse_qs(urlparse(url).query).get("id", [""])[0]
    if not file_id:
        raise ValueError("Google Drive URL has no id parameter")
    return file_id


def name_from_headers(headers: object, fallback: str) -> str:
    value = headers.get("Content-Disposition", "")
    match = re.search(r"filename\*?=(?:UTF-8''|\")?([^;\"]+)", value, re.I)
    if not match:
        return fallback
    name = match.group(1).strip().strip('"')
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name) or fallback


def unique_path(directory: Path, name: str) -> Path:
    candidate = directory / name
    counter = 2
    while candidate.exists():
        candidate = directory / f"{Path(name).stem}-{counter}{Path(name).suffix}"
        counter += 1
    return candidate


def download(url: str, index: int) -> tuple[str, int, str]:
    file_id = file_id_from_url(url)
    request_url = (
        "https://drive.usercontent.google.com/download?"
        f"id={file_id}&export=download&confirm=t"
    )
    opener = build_opener(HTTPCookieProcessor())
    request = Request(request_url, headers={"User-Agent": "Mozilla/5.0"})
    with opener.open(request, timeout=90) as response:
        content_type = response.headers.get_content_type()
        if content_type == "text/html":
            body = response.read(512).decode("utf-8", "replace")
            raise RuntimeError(f"Google Drive returned HTML: {body[:160]!r}")
        target = unique_path(COMPONENTS_DIR, name_from_headers(response.headers, f"{index:03d}-{file_id}"))
        size = 0
        with target.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                size += len(chunk)
    return target.name, size, content_type


def main() -> int:
    COMPONENTS_DIR.mkdir(exist_ok=True)
    links = [line.strip() for line in LINKS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    start_at = int(sys.argv[1]) if len(sys.argv) == 2 else 1
    if start_at < 1 or start_at > len(links) + 1:
        raise ValueError(f"Start index must be between 1 and {len(links) + 1}")
    rows: list[dict[str, object]] = []
    pending = list(enumerate(links[start_at - 1 :], start=start_at))
    # Google Drive serves these independent assets reliably in a small parallel batch.
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(download, url, index): (index, url) for index, url in pending}
        for future in as_completed(futures):
            index, url = futures[future]
            try:
                filename, size, content_type = future.result()
                rows.append({"index": index, "url": url, "status": "downloaded", "filename": filename, "bytes": size, "content_type": content_type, "error": ""})
                print(f"[{index}/{len(links)}] downloaded {filename} ({size:,} bytes)", flush=True)
            except Exception as error:  # Continue to report every missing asset.
                rows.append({"index": index, "url": url, "status": "failed", "filename": "", "bytes": 0, "content_type": "", "error": str(error)})
                print(f"[{index}/{len(links)}] FAILED: {error}", file=sys.stderr, flush=True)

    with AUDIT_PATH.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=["index", "url", "status", "filename", "bytes", "content_type", "error"])
        writer.writeheader()
        writer.writerows(rows)

    rows.sort(key=lambda row: int(row["index"]))
    failures = sum(row["status"] != "downloaded" for row in rows)
    print(f"Finished batch: {len(rows) - failures}/{len(rows)} downloaded. Audit: {AUDIT_PATH}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
