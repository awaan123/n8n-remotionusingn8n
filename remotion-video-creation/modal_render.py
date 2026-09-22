import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import modal


APP_NAME = "remotion-bulk-renderer"

app = modal.App(APP_NAME)

# Stable base image. Dependency or browser changes rebuild this layer, while
# source files are mounted afterward so ordinary TSX edits do not rerun npm ci.
image = (
    modal.Image.from_registry(
        "node:20-bookworm-slim",
        add_python="3.12",
    )
    .apt_install(
        "ffmpeg",
        "ca-certificates",
        "fonts-liberation",
        "libasound2",
        "libatk-bridge2.0-0",
        "libatk1.0-0",
        "libcairo2",
        "libcups2",
        "libdbus-1-3",
        "libdrm2",
        "libgbm1",
        "libglib2.0-0",
        "libgtk-3-0",
        "libnspr4",
        "libnss3",
        "libpango-1.0-0",
        "libx11-6",
        "libx11-xcb1",
        "libxcb1",
        "libxcomposite1",
        "libxdamage1",
        "libxext6",
        "libxfixes3",
        "libxkbcommon0",
        "libxrandr2",
        "libxshmfence1",
    )
    .add_local_file("package.json", "/app/package.json", copy=True)
    .add_local_file("package-lock.json", "/app/package-lock.json", copy=True)
    .workdir("/app")
    .run_commands(
        "npm ci",
        "npx remotion browser ensure",
    )
    .add_local_dir(
        ".",
        remote_path="/app",
        ignore=[
            "node_modules",
            ".git",
            "out",
            "renders",
            "__pycache__",
            ".venv",
        ],
    )
)

# Persist completed MP4 files across containers and runs.
renders_volume = modal.Volume.from_name(
    "remotion-renders",
    create_if_missing=True,
    version=2,
)


@app.function(
    image=image,
    cpu=(2.0, 2.0),
    memory=(4096, 4096),
    max_containers=13,
    min_containers=0,
    timeout=3600,
    retries=1,
    volumes={"/renders": renders_volume},
)
def render_video(job: dict[str, Any]) -> str:
    job_id = str(job["id"])
    render_folder = str(job["render_folder"])
    composition_id = str(job["composition_id"])
    target_width = int(job["target_width"])
    target_height = int(job["target_height"])
    scale = float(job["scale"])

    safe_id = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in job_id
    )
    safe_folder = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in render_folder
    )
    if not safe_folder or safe_folder != render_folder:
        raise ValueError(f"Unsafe render folder: {render_folder!r}")

    props_path = Path(f"/tmp/{safe_id}-props.json")
    renders_dir = Path("/renders") / safe_folder
    renders_dir.mkdir(parents=True, exist_ok=True)
    output_path = renders_dir / f"{safe_id}.mp4"

    if output_path.exists():
        raise FileExistsError(f"Refusing to replace existing render: {output_path}")

    props_path.write_text(
        json.dumps(job.get("props", {})),
        encoding="utf-8",
    )

    command = [
        "npx",
        "remotion",
        "render",
        composition_id,
        str(output_path),
        "--props",
        str(props_path),
        "--codec",
        "h264",
        "--image-format",
        "jpeg",
        "--concurrency",
        "2",
        "--x264-preset",
        "veryfast",
        "--scale",
        str(scale),
    ]

    subprocess.run(
        command,
        cwd="/app",
        check=True,
    )

    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,codec_name",
            "-of",
            "json",
            str(output_path),
        ],
        cwd="/app",
        capture_output=True,
        text=True,
        check=True,
    )
    streams = json.loads(probe.stdout).get("streams", [])
    if not streams:
        raise RuntimeError(f"No video stream found in {output_path}")
    width = int(streams[0].get("width", 0))
    height = int(streams[0].get("height", 0))
    if width != target_width or height != target_height:
        raise RuntimeError(
            f"{composition_id} rendered at {width}x{height}; "
            f"expected {target_width}x{target_height}"
        )

    renders_volume.commit()
    return f"{safe_folder}/{output_path.name}"


@app.local_entrypoint()
def main() -> None:
    # Completed compositions were removed after their local MP4s were verified.
    # Add only new, unrendered compositions to this list.
    jobs = []

    if not jobs:
        print("No pending compositions. All completed render jobs were removed.")
        return

    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        + "-"
        + uuid4().hex[:8]
    )
    for job in jobs:
        job["id"] = f"{job['id']}-{run_id}"
        job["render_folder"] = run_id

    results = list(render_video.map(jobs))

    print("\nCompleted videos:")
    for result in results:
        print(result)
