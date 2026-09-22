"""Render every current Remotion composition locally and verify each MP4.

Usage:
    npm run render:local
    npm run render:local:native

The command is restart-safe: valid existing outputs are skipped, invalid existing
outputs are reported as conflicts, and no source file or MP4 is ever deleted.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


SAFE_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_-]+")


@dataclass(frozen=True)
class RenderJob:
    row: str
    source_file: str
    composition_id: str
    entry_file: str
    output_path: Path
    width: int
    height: int
    scale: float
    target_width: int
    target_height: int


def safe_name(value: str) -> str:
    result = SAFE_NAME_PATTERN.sub("-", value).strip("-")
    if not result:
        raise ValueError(f"Could not create a safe filename from '{value}'")
    return result


def even(value: float) -> int:
    return max(2, round(value / 2) * 2)


def adobe_stock_target(width: int, height: int) -> tuple[int, int, float]:
    if width == height:
        target = 2160 if width > 1080 else 1080
        return target, target, target / width
    if width > height:
        return 3840, 2160, 3840 / width
    return 2160, 3840, 3840 / height


def load_composition_dimensions(
    project_dir: Path,
    npx: str,
    entry_file: str,
) -> dict[str, tuple[int, int]]:
    result = subprocess.run(
        [npx, "remotion", "compositions", entry_file],
        cwd=project_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Could not enumerate Remotion compositions:\n"
            + result.stdout
            + result.stderr
        )
    output = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", result.stdout)
    dimensions: dict[str, tuple[int, int]] = {}
    pattern = re.compile(r"^([A-Za-z0-9_-]+)\s+\d+\s+(\d+)x(\d+)\s+\d+", re.MULTILINE)
    for match in pattern.finditer(output):
        dimensions[match.group(1)] = (int(match.group(2)), int(match.group(3)))
    if not dimensions:
        raise RuntimeError("Remotion returned no compositions")
    return dimensions


def load_jobs(
    project_dir: Path,
    profile: str,
    max_edge: int | None,
    npx: str,
    only_row: str | None,
    folder_name: str | None = None,
) -> list[RenderJob]:
    status_path = project_dir.parent / "components" / "component-status.csv"
    payload_dir = status_path.parent
    renders_dir = project_dir / "renders" / (folder_name if folder_name else f"local-{profile}")
    with status_path.open(newline="", encoding="utf-8-sig") as file:
        rows = [
            item
            for item in csv.DictReader(file)
            if (payload_dir / item["SourceFile"]).is_file()
            and item["Status"] in {"registered", "render_failed", "rendered_needs_rerender"}
            and (only_row is None or item["Row"] == only_row.zfill(3))
        ]

    jobs: list[RenderJob] = []
    for item in rows:
        source_file = item["SourceFile"]
        row = item["Row"]
        composition_id = item["CompositionId"]
        entry_file = item["EntryFile"]
        try:
            dimensions = load_composition_dimensions(project_dir, npx, entry_file)
        except Exception as error:
            update_component_status(
                status_path,
                source_file,
                "render_failed",
                f"composition preflight failed: {error}",
            )
            print(f"PRE-FLIGHT FAILED {row} {composition_id}: {error}", file=sys.stderr)
            continue
        if composition_id not in dimensions:
            raise ValueError(f"No Root.tsx dimensions found for {composition_id}")
        width, height = dimensions[composition_id]
        if profile == "adobe-stock":
            target_width, target_height, scale = adobe_stock_target(width, height)
        else:
            scale = 1.0 if max_edge is None else max_edge / max(width, height)
            target_width = even(width * scale)
            target_height = even(height * scale)
        output_path = renders_dir / f"{row}-{safe_name(composition_id)}-{profile}.mp4"
        jobs.append(
            RenderJob(
                row,
                source_file,
                composition_id,
                entry_file,
                output_path,
                width,
                height,
                scale,
                target_width,
                target_height,
            )
        )

    output_paths = [job.output_path.name.casefold() for job in jobs]
    if len(output_paths) != len(set(output_paths)):
        raise ValueError("Planned local render filenames are not unique")
    return jobs


def probe_video(path: Path, ffprobe: Path) -> dict[str, object] | None:
    if not ffprobe.is_file() or not path.is_file() or path.stat().st_size == 0:
        return None
    result = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,duration,nb_frames",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    streams = payload.get("streams")
    if not isinstance(streams, list) or not streams:
        return None
    stream = streams[0]
    if not isinstance(stream, dict) or not stream.get("codec_name"):
        return None
    return stream


def write_manifest(path: Path, records: list[dict[str, object]]) -> None:
    fieldnames = [
        "Row",
        "SourceFile",
        "CompositionId",
        "OutputFile",
        "TargetWidth",
        "TargetHeight",
        "Status",
        "ExitCode",
        "SizeBytes",
    ]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def update_component_status(
    status_path: Path,
    source_file: str,
    status: str,
    note: str,
) -> None:
    with status_path.open(newline="", encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file))
        fieldnames = list(file.readline() for _ in [])
    if not rows:
        raise RuntimeError(f"No rows found in {status_path}")
    fieldnames = list(rows[0].keys())
    for row in rows:
        if row["SourceFile"] == source_file:
            row["Status"] = status
            row["Notes"] = note
            break
    else:
        raise ValueError(f"No CSV row found for {source_file}")
    with status_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render all Remotion videos locally")
    parser.add_argument("--only-row", help="Render only one three-digit source row")
    parser.add_argument(
        "--adobe-stock",
        action="store_true",
        help="Render square videos at 1080x1080 and horizontal videos at 3840x2160",
    )
    parser.add_argument(
        "--native",
        action="store_true",
        help="Render at native composition dimensions instead of Adobe Stock targets",
    )
    parser.add_argument(
        "--max-edge",
        type=int,
        help="Scale the longest output edge to this size; incompatible with --adobe-stock",
    )
    parser.add_argument(
        "--folder-name",
        help="Custom subfolder inside renders/ to save output files",
    )
    args = parser.parse_args()
    if args.max_edge is not None and args.max_edge < 1:
        raise ValueError("--max-edge must be a positive integer")
    if args.adobe_stock and args.native:
        raise ValueError("--adobe-stock and --native cannot be combined")
    if args.adobe_stock and args.max_edge is not None:
        raise ValueError("--max-edge cannot be combined with --adobe-stock")

    project_dir = Path(__file__).resolve().parent
    profile = (
        "native"
        if args.native
        else f"{args.max_edge}px"
        if args.max_edge is not None
        else "adobe-stock"
    )
    folder_name = args.folder_name if args.folder_name else f"local-{profile}"
    renders_dir = project_dir / "renders" / folder_name
    renders_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = renders_dir / "local-render-status.csv"
    status_path = project_dir.parent / "components" / "component-status.csv"
    npx = shutil.which("npx")
    if npx is None:
        raise RuntimeError("npx was not found on PATH")
    binaries_dir = project_dir / ".remotion-binaries"
    ffprobe_path = binaries_dir / "ffprobe.exe"
    if not ffprobe_path.is_file():
        packaged_ffprobe = (
            project_dir
            / "node_modules"
            / "@remotion"
            / "compositor-win32-x64-msvc"
            / "ffprobe.exe"
        )
        if packaged_ffprobe.is_file():
            ffprobe_path = packaged_ffprobe
        found_ffprobe = shutil.which("ffprobe")
        if not ffprobe_path.is_file() and found_ffprobe is None:
            raise RuntimeError("ffprobe was not found on PATH")
        ffprobe = ffprobe_path if ffprobe_path.is_file() else Path(found_ffprobe)
    else:
        ffprobe = ffprobe_path
    jobs = load_jobs(project_dir, profile, args.max_edge, npx, args.only_row, folder_name=folder_name)
    if args.only_row and not jobs:
        raise ValueError(f"No render job found for row {args.only_row}")

    records: list[dict[str, object]] = []
    failures = 0
    for index, job in enumerate(jobs, start=1):
        existing_probe = probe_video(job.output_path, ffprobe)
        existing_matches_target = (
            existing_probe is not None
            and int(existing_probe.get("width", 0)) == job.target_width
            and int(existing_probe.get("height", 0)) == job.target_height
        )
        if existing_matches_target:
            print(f"[{index}/{len(jobs)}] SKIP valid existing {job.output_path.name}")
            records.append(
                {
                    "Row": job.row,
                    "SourceFile": job.source_file,
                    "CompositionId": job.composition_id,
                    "OutputFile": job.output_path.name,
                    "TargetWidth": job.target_width,
                    "TargetHeight": job.target_height,
                    "Status": "skipped_valid_existing",
                    "ExitCode": 0,
                    "SizeBytes": job.output_path.stat().st_size,
                }
            )
            write_manifest(manifest_path, records)
            update_component_status(
                status_path,
                job.source_file,
                "rendered_verified",
                f"verified local render {job.target_width}x{job.target_height}",
            )
            continue

        if job.output_path.exists():
            print(f"[{index}/{len(jobs)}] BLOCK invalid existing {job.output_path.name}")
            failures += 1
            records.append(
                {
                    "Row": job.row,
                    "SourceFile": job.source_file,
                    "CompositionId": job.composition_id,
                    "OutputFile": job.output_path.name,
                    "TargetWidth": job.target_width,
                    "TargetHeight": job.target_height,
                    "Status": "blocked_invalid_existing",
                    "ExitCode": -1,
                    "SizeBytes": job.output_path.stat().st_size,
                }
            )
            write_manifest(manifest_path, records)
            continue

        print(
            f"[{index}/{len(jobs)}] RENDER {job.composition_id} "
            f"at {job.target_width}x{job.target_height} -> {job.output_path.name}"
        )
        command = [
            npx,
            "remotion",
            "render",
            job.entry_file,
            job.composition_id,
            str(job.output_path),
            "--codec=h264",
            "--muted",
            "--image-format=jpeg",
            f"--scale={job.scale!r}",
            "--concurrency=1",
            "--crf=18",
            "--x264-preset=veryfast",
        ]
        if (binaries_dir / "ffmpeg.exe").is_file():
            command.insert(-5, f"--binaries-directory={binaries_dir}")
        result = subprocess.run(command, cwd=project_dir, check=False)
        probe = probe_video(job.output_path, ffprobe)
        success = (
            result.returncode == 0
            and probe is not None
            and int(probe.get("width", 0)) == job.target_width
            and int(probe.get("height", 0)) == job.target_height
        )
        if not success:
            failures += 1
        status = "rendered_verified" if success else "render_failed"
        if (
            probe is not None
            and result.returncode == 0
            and status != "rendered_verified"
        ):
            status = "rendered_needs_rerender"
        records.append(
            {
                "Row": job.row,
                "SourceFile": job.source_file,
                "CompositionId": job.composition_id,
                "OutputFile": job.output_path.name,
                "TargetWidth": job.target_width,
                "TargetHeight": job.target_height,
                "Status": status,
                "ExitCode": result.returncode,
                "SizeBytes": job.output_path.stat().st_size if job.output_path.exists() else 0,
            }
        )
        write_manifest(manifest_path, records)
        update_component_status(
            status_path,
            job.source_file,
            status,
            f"local render {job.target_width}x{job.target_height}",
        )

    print(f"Completed {len(jobs)} job(s); failures={failures}; manifest={manifest_path}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
