"""
download_renders.py

Downloads all rendered MP4s from the Modal 'remotion-renders' volume directly
to:

    remotion-video-creation/renders/

Required remote and local layout:
  Video.mp4 -> remotion-video-creation/renders/Video.mp4

Legacy remote subfolders are flattened into the same local renders folder.

Safety guarantees:
  1. Downloads to a .tmp file first.
  2. Verifies local file size matches remote size exactly.
  3. Atomically installs the final file without replacing an existing MP4.
  4. Adds _2, _3, and so on if a local filename already exists.
  5. Deletes a remote file only after its local copy is verified.
  6. Reports verified downloads and successful deletions separately.

Usage:
    python download_renders.py

Optional flags:
    --dry-run     List files without downloading or deleting
"""

import argparse
import os
import sys
from pathlib import Path, PurePosixPath
from uuid import uuid4

import modal

VOLUME_NAME = "remotion-renders"


def parse_remote_render_path(remote_path: str) -> str:
    """Validate a remote MP4 path and return its filename."""
    normalized_path = remote_path.replace("\\", "/").lstrip("/")
    parts = PurePosixPath(normalized_path).parts

    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("remote render path must be a safe relative MP4 path")

    filename = parts[-1]
    if not filename.lower().endswith(".mp4") or filename in {".mp4", "..mp4"}:
        raise ValueError(f"invalid MP4 filename '{filename}'")

    return filename


def get_unique_output_path(output_dir: Path, filename: str, index: int = 1) -> Path:
    """Return a destination name while preserving the .mp4 extension."""
    source = Path(filename)
    suffix = "" if index == 1 else f"_{index}"
    return output_dir / f"{source.stem}{suffix}{source.suffix}"


def download_and_verify(
    vol: modal.Volume,
    remote_path: str,
    remote_size: int,
    output_dir: Path,
) -> Path | None:
    """
    Download one file to a temporary path, verify its size, and publish it
    without replacing an existing local MP4.
    """
    filename = parse_remote_render_path(remote_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    temp_path = output_dir / f".{filename}.{uuid4().hex}.tmp"

    try:
        with temp_path.open("wb") as file:
            for chunk in vol.read_file(remote_path):
                file.write(chunk)
    except Exception as exc:
        print(f"    [FAIL] Download error: {exc}")
        temp_path.unlink(missing_ok=True)
        return None

    local_size = temp_path.stat().st_size
    if local_size != remote_size:
        print(
            f"    [FAIL] Size mismatch! "
            f"remote={remote_size} bytes, local={local_size} bytes"
        )
        temp_path.unlink(missing_ok=True)
        return None

    index = 1
    while True:
        final_path = get_unique_output_path(output_dir, filename, index)
        try:
            # Creating a hard link is atomic and raises FileExistsError rather
            # than replacing an existing video.
            os.link(temp_path, final_path)
            temp_path.unlink()
            break
        except FileExistsError:
            index += 1
        except Exception as exc:
            print(f"    [FAIL] Could not install verified file: {exc}")
            temp_path.unlink(missing_ok=True)
            return None

    return final_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and clean Modal renders")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files without downloading or deleting",
    )
    args = parser.parse_args()
    dry_run: bool = args.dry_run

    script_dir = Path(__file__).resolve().parent
    renders_root = script_dir / "renders"

    try:
        volume = modal.Volume.from_name(VOLUME_NAME, version=2)
    except Exception as exc:
        print(f"[ERROR] Could not connect to volume '{VOLUME_NAME}': {exc}")
        sys.exit(1)

    try:
        entries = list(volume.listdir("/", recursive=True))
    except Exception as exc:
        print(f"[ERROR] Could not list volume contents: {exc}")
        sys.exit(1)

    if not entries:
        print(f"Volume '{VOLUME_NAME}' is empty — nothing to download.")
        return

    mp4_files = [entry for entry in entries if entry.path.lower().endswith(".mp4")]

    if not mp4_files:
        print(f"No .mp4 files found in volume '{VOLUME_NAME}'.")
        return

    valid_files = []
    invalid_paths: list[str] = []

    print(f"Found {len(mp4_files)} video(s) in '{VOLUME_NAME}':")
    for entry in mp4_files:
        try:
            filename = parse_remote_render_path(entry.path)
        except ValueError as exc:
            print(f"  [INVALID] {entry.path}: {exc}")
            invalid_paths.append(entry.path)
            continue

        valid_files.append(entry)
        print(
            f"  {entry.path}  ({entry.size / 1024:.1f} KB) "
            f"-> renders/{filename}"
        )

    if dry_run:
        print("\n[DRY RUN] No files downloaded or deleted.")
        if invalid_paths:
            sys.exit(1)
        return

    verified: dict[str, Path] = {}
    download_failed: list[str] = []

    print()
    for entry in valid_files:
        remote_path: str = entry.path
        remote_size: int = entry.size

        print(
            f"Downloading  {remote_path}  ({remote_size / 1024:.1f} KB) ...",
            flush=True,
        )

        local_path = download_and_verify(
            volume,
            remote_path,
            remote_size,
            renders_root,
        )

        if local_path is not None:
            print(f"    [OK] Verified → {local_path}")
            verified[remote_path] = local_path
        else:
            print(f"    Kept on Modal because download failed: {remote_path}")
            download_failed.append(remote_path)

    deleted: list[str] = []
    delete_failed: list[str] = []

    if verified:
        print(f"\nDeleting {len(verified)} verified file(s) from Modal volume...")
        for remote_path, local_path in verified.items():
            try:
                volume.remove_file(remote_path)
                deleted.append(remote_path)
                print(f"  Deleted from volume: {remote_path}")
            except Exception as exc:
                delete_failed.append(remote_path)
                print(
                    f"  [WARNING] Could not delete '{remote_path}' from volume.\n"
                    f"  Local copy is intact at: {local_path}\n"
                    f"  Error: {exc}"
                )

    print("\n" + "=" * 54)
    print(f"  Downloaded & verified : {len(verified)} file(s)")
    print(f"  Deleted from Modal    : {len(deleted)} file(s)")
    print(f"  Invalid remote paths  : {len(invalid_paths)} file(s)")
    print(f"  Download failures     : {len(download_failed)} file(s)")
    print(f"  Delete failures       : {len(delete_failed)} file(s)")

    for label, paths in (
        ("Invalid path", invalid_paths),
        ("Download failed", download_failed),
        ("Delete failed", delete_failed),
    ):
        for path in paths:
            print(f"    - {label}: {path}")

    print("=" * 54)

    if invalid_paths or download_failed or delete_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
