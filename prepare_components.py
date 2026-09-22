"""Rebuild isolated Remotion sources from the downloaded component payloads."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
COMPONENTS_DIR = ROOT / "components"
PROJECT_DIR = ROOT / "remotion-video-creation"
VIDEOS_DIR = PROJECT_DIR / "src" / "videos"
ENTRIES_DIR = PROJECT_DIR / "src" / "entries"
STATUS_PATH = COMPONENTS_DIR / "component-status.csv"

CODE_BLOCK = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
SOURCE_PATH = re.compile(
    r"^\s*//\s*(?:File:\s*)?((?:src/)?[A-Za-z0-9_./-]+\.(?:tsx|ts|jsx|js|css))\s*$"
)
HEADING_PATH = re.compile(r"\*\*((?:src/)?[A-Za-z0-9_./-]+\.(?:tsx|ts|jsx|js|css))\*\*\s*$")
MARKDOWN_PATH = re.compile(r"^#{1,6}\s+((?:src/)?[A-Za-z0-9_./-]+\.(?:tsx|ts|jsx|js|css))\s*$", re.MULTILINE)
PATH_TOKEN = re.compile(r"((?:src/)?[A-Za-z0-9_./-]+\.(?:tsx|ts|jsx|js|css))")
COMPOSITION_ID = re.compile(r"<Composition\b[^>]*\bid\s*=\s*[\"']([^\"']+)[\"']", re.DOTALL)
DEFAULT_EXPORT = re.compile(r"export\s+default\s+(?:function\s+)?([A-Za-z_][A-Za-z0-9_]*)")
NAMED_EXPORT = re.compile(r"export\s+(?:const|function|class)\s+([A-Za-z_][A-Za-z0-9_]*)")
VIEW_BOX = re.compile(r"viewBox\s*=\s*[\"']0\s+0\s+(\d+)\s+(\d+)[\"']")
LOCAL_IMPORT = re.compile(r"(from\s+[\"'])(\.[^\"']+)([\"'])")


def payload_content(path: Path) -> str:
    parsed: Any = json.loads(path.read_text(encoding="utf-8"))
    item = parsed[0]
    response = item["data"] if "data" in item else item
    return str(response["choices"][0]["message"]["content"])


def source_blocks(content: str) -> dict[str, str]:
    blocks: dict[str, str] = {}
    for match in CODE_BLOCK.finditer(content):
        block = match.group(1)
        lines = block.splitlines()
        if not lines:
            continue
        source_match = SOURCE_PATH.match(lines[0])
        if source_match:
            source_path = source_match.group(1)
            body = "\n".join(lines[1:])
        else:
            nearby = content[max(0, match.start() - 300) : match.start()]
            heading_match = HEADING_PATH.search(nearby) or MARKDOWN_PATH.search(nearby)
            if heading_match:
                source_path = heading_match.group(1)
            else:
                paths = PATH_TOKEN.findall(nearby)
                if not paths:
                    if not re.search(r"\b(?:import|export|const|function|interface|type)\b", block):
                        continue
                    source_path = f"Unlabeled{len(blocks) + 1}.tsx"
                else:
                    source_path = paths[-1]
            body = "\n".join(lines)
        if any(character in body for character in "\u251c\u2514\u2502"):
            continue
        if not re.search(r"\b(?:import|export|const|function|interface|type)\b", body):
            continue
        if not source_path:
            continue
        if source_path.startswith("src/"):
            source_path = source_path.removeprefix("src/")
        if ".." in Path(source_path).parts:
            raise ValueError(f"Unsafe source path: {source_path}")
        blocks[source_path] = body.strip() + "\n"
    return blocks


def unique_payloads() -> list[Path]:
    payloads = [
        path
        for path in COMPONENTS_DIR.iterdir()
        if path.is_file() and path.name not in {"component-status.csv", "download-audit.csv"}
    ]
    seen: set[str] = set()
    unique: list[Path] = []
    for path in sorted(payloads, key=lambda item: item.name):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest not in seen:
            seen.add(digest)
            unique.append(path)
    return unique


def synthesize_root(blocks: dict[str, str], index: int, payload_name: str) -> tuple[str, str]:
    def candidate_score(path: str) -> tuple[int, int]:
        source = blocks[path]
        stem = Path(path).stem.lower()
        names = NAMED_EXPORT.findall(source)
        score = 0
        if "composition" in stem:
            score += 100
        if stem == "index":
            score += 90
        if "animation" in stem:
            score += 80
        if "scene" in stem:
            score += 70
        if any(name.endswith("Composition") for name in names):
            score += 60
        if DEFAULT_EXPORT.search(source):
            score += 40
        if re.search(r"return\s*\([\s\S]*<", source):
            score += 20
        return score, -len(Path(path).parts)

    candidates = [
        path
        for path, source in blocks.items()
        if DEFAULT_EXPORT.search(source) or NAMED_EXPORT.search(source)
    ]
    main_path = max(candidates, key=candidate_score) if candidates else None
    if main_path is None:
        raise RuntimeError(f"{payload_name} has no exportable composition: {list(blocks)}")
    default_match = DEFAULT_EXPORT.search(blocks[main_path])
    use_default_import = default_match is not None
    if use_default_import:
        component_name = default_match.group(1)
    else:
        names = NAMED_EXPORT.findall(blocks[main_path])
        component_names = [
            name
            for name in names
            if not re.search(
                rf"export\s+const\s+{re.escape(name)}\s*=\s*\{{",
                blocks[main_path],
            )
        ]
        if not component_names:
            raise RuntimeError(f"{payload_name} has no React component export in {main_path}")
        component_name = next(
            (name for name in reversed(component_names) if name.endswith("Composition")),
            component_names[-1],
        )
    component_id = re.sub(r"[^A-Za-z0-9_-]+", "-", component_name).strip("-") or f"Video{index:03d}"
    view_box = next((VIEW_BOX.search(source) for source in blocks.values() if VIEW_BOX.search(source)), None)
    width, height = (1080, 1080)
    if view_box:
        source_width, source_height = (int(view_box.group(1)), int(view_box.group(2)))
        if source_width > source_height:
            width, height = (1920, 1080)
        elif source_height > source_width:
            width, height = (1080, 1920)
    import_path = "./" + str(Path(main_path).with_suffix("")).replace("\\", "/")
    embedded_ids = COMPOSITION_ID.findall(blocks[main_path])
    if len(embedded_ids) == 1:
        forwarded_root = "\n".join(
            [
                (
                    f'import {component_name} from "{import_path}";'
                    if use_default_import
                    else f'import {{ {component_name} }} from "{import_path}";'
                ),
                f"export const Root = {component_name};",
                "",
            ]
        )
        return forwarded_root, embedded_ids[0]
    root = "\n".join(
        [
            'import React from "react";',
            'import { Composition } from "remotion";',
            (
                f'import {component_name} from "{import_path}";'
                if use_default_import
                else f'import {{ {component_name} }} from "{import_path}";'
            ),
            "",
            "export const Root: React.FC = () => (",
            f'  <Composition id="{component_id}" component={{{component_name}}} durationInFrames={{180}} fps={{30}} width={{{width}}} height={{{height}}} />',
            ");",
            "",
        ]
    )
    return root, component_id


def normalize_root_export(root_source: str) -> str:
    if re.search(r"export\s+const\s+Root\b", root_source):
        return root_source
    names = NAMED_EXPORT.findall(root_source)
    root_name = next((name for name in names if name.endswith("Root")), None)
    if root_name:
        return root_source + f"\nexport {{ {root_name} as Root }};\n"
    if "export default" in root_source:
        return root_source + "\nexport { default as Root };\n"
    raise RuntimeError("Root.tsx has no exportable composition root")


def repair_relative_imports(folder: Path) -> None:
    source_files = list(folder.rglob("*.ts")) + list(folder.rglob("*.tsx"))
    for source_file in source_files:
        source = source_file.read_text(encoding="utf-8")

        def repair(match: re.Match[str]) -> str:
            specifier = match.group(2)
            expected = source_file.parent / specifier
            if any(expected.with_suffix(extension).is_file() for extension in (".ts", ".tsx", ".js", ".jsx")):
                return match.group(0)
            basename = Path(specifier).name
            candidates = [
                candidate
                for candidate in source_files
                if candidate.stem == basename and candidate != source_file
            ]
            if len(candidates) != 1:
                return match.group(0)
            relative = os.path.relpath(candidates[0].with_suffix(""), source_file.parent).replace("\\", "/")
            if not relative.startswith("."):
                relative = "./" + relative
            return f"{match.group(1)}{relative}{match.group(3)}"

        repaired = LOCAL_IMPORT.sub(repair, source)
        if repaired != source:
            source_file.write_text(repaired, encoding="utf-8", newline="\n")


def adobe_stock_target(width: int, height: int) -> tuple[int, int, float]:
    if width == height:
        target = 2160 if width > 1080 else 1080
        return target, target, round(target / width, 4)
    if width > height:
        return 3840, 2160, round(3840 / width, 4)
    return 2160, 3840, round(3840 / height, 4)


def get_composition_dimensions(root_source: str, blocks: dict[str, str]) -> tuple[int, int]:
    w_match = re.search(r"\bwidth\s*=\s*\{?(\d+)\}?", root_source)
    h_match = re.search(r"\bheight\s*=\s*\{?(\d+)\}?", root_source)
    if w_match and h_match:
        return int(w_match.group(1)), int(h_match.group(1))
    view_box = next((VIEW_BOX.search(source) for source in blocks.values() if VIEW_BOX.search(source)), None)
    if view_box:
        sw, sh = int(view_box.group(1)), int(view_box.group(2))
        if sw > sh:
            return 1920, 1080
        elif sh > sw:
            return 1080, 1920
    return 1080, 1080


def update_modal_render_jobs(jobs: list[dict[str, Any]]) -> None:
    modal_path = PROJECT_DIR / "modal_render.py"
    if not modal_path.exists():
        print(f"Warning: {modal_path} not found")
        return
    content = modal_path.read_text(encoding="utf-8")
    
    # Format jobs as python list literal
    jobs_formatted = json.dumps(jobs, indent=8)
    # Replace jobs list inside main()
    pattern = re.compile(r"(def main\(\) -> None:\s+.*?jobs = )\[.*?\](\n\n\s+if not jobs:)", re.DOTALL)
    if pattern.search(content):
        new_content = pattern.sub(rf"\g<1>{jobs_formatted}\g<2>", content)
        modal_path.write_text(new_content, encoding="utf-8", newline="\n")
        print(f"Updated {modal_path.name} with {len(jobs)} render jobs")
    else:
        print(f"Warning: Could not match jobs pattern in {modal_path.name}")


def main() -> None:
    payloads = unique_payloads()
    if not payloads:
        raise RuntimeError(f"Expected at least 1 payload, found {len(payloads)}")

    if VIDEOS_DIR.exists():
        shutil.rmtree(VIDEOS_DIR)
    VIDEOS_DIR.mkdir(parents=True)
    if ENTRIES_DIR.exists():
        shutil.rmtree(ENTRIES_DIR)
    ENTRIES_DIR.mkdir(parents=True)

    rows: list[dict[str, str]] = []
    registrations: list[str] = []
    composition_ids: set[str] = set()
    modal_jobs: list[dict[str, Any]] = []
    valid_count = 0

    for index, payload in enumerate(payloads, start=1):
        try:
            raw = payload_content(payload)
            blocks = source_blocks(raw)
            if not blocks:
                rows.append({
                    "Row": f"{index:03d}",
                    "SourceFile": payload.name,
                    "CompositionId": "N/A",
                    "EntryFile": "N/A",
                    "Status": "invalid_payload",
                    "Notes": "No TSX source code blocks found in payload response",
                })
                continue

            root_source = blocks.get("Root.tsx")
            forwarded_nested_root = False
            if root_source is None:
                nested_root_path = next(
                    (path for path in blocks if Path(path).name == "Root.tsx"),
                    None,
                )
                if nested_root_path is not None:
                    nested_ids = COMPOSITION_ID.findall(blocks[nested_root_path])
                    if len(nested_ids) == 1:
                        composition_id = nested_ids[0]
                        import_path = "./" + str(Path(nested_root_path).with_suffix("")).replace("\\", "/")
                        root_source = (
                            f'import {{ Root as NestedRoot }} from "{import_path}";\n'
                            "export const Root = NestedRoot;\n"
                        )
                        blocks["Root.tsx"] = root_source
                        forwarded_nested_root = True
            if root_source:
                if not forwarded_nested_root:
                    ids = COMPOSITION_ID.findall(root_source)
                    if len(ids) == 1:
                        composition_id = ids[0]
                    elif len(ids) == 0:
                        root_source, composition_id = synthesize_root(blocks, index, payload.name)
                        blocks["Root.tsx"] = root_source
                    else:
                        composition_id = ids[0]
            else:
                root_source, composition_id = synthesize_root(blocks, index, payload.name)
                blocks["Root.tsx"] = root_source

            if composition_id in composition_ids:
                composition_id = f"{composition_id}-{index:03d}"
                root_source = re.sub(
                    r"(<Composition\b[^>]*\bid\s*=\s*[\"'])[^\"']+",
                    rf"\g<1>{composition_id}",
                    root_source,
                    count=1,
                )
                blocks["Root.tsx"] = root_source

            composition_ids.add(composition_id)
            blocks["Root.tsx"] = normalize_root_export(blocks["Root.tsx"])

            width, height = get_composition_dimensions(blocks["Root.tsx"], blocks)
            target_w, target_h, scale = adobe_stock_target(width, height)

            folder = f"{index:03d}-{re.sub(r'[^A-Za-z0-9_-]+', '-', composition_id).strip('-')}"
            for source_path, source in blocks.items():
                if source_path.endswith(".ts") and ("<" in source and ("/>" in source or "</" in source)):
                    source_path = source_path[:-3] + ".tsx"
                target = VIDEOS_DIR / folder / source_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("// @ts-nocheck\n/* eslint-disable */\n" + source, encoding="utf-8", newline="\n")
            repair_relative_imports(VIDEOS_DIR / folder)

            entry_file = f"src/entries/{index:03d}.tsx"
            (PROJECT_DIR / entry_file).write_text(
                "\n".join([
                    'import { registerRoot } from "remotion";',
                    f'import {{ Root }} from "../videos/{folder}/Root";',
                    "",
                    "registerRoot(Root);",
                    "",
                ]),
                encoding="utf-8",
                newline="\n",
            )

            valid_count += 1
            alias = f"Video{valid_count:03d}"
            registrations.append(f'import * as {alias} from "./videos/{folder}/Root";')

            modal_jobs.append({
                "id": f"{index:03d}-{composition_id}",
                "composition_id": composition_id,
                "target_width": target_w,
                "target_height": target_h,
                "scale": scale,
            })

            rows.append({
                "Row": f"{index:03d}",
                "SourceFile": payload.name,
                "CompositionId": composition_id,
                "EntryFile": entry_file,
                "Status": "prepared",
                "Notes": f"Recovered {len(blocks)} source file(s) ({width}x{height} -> {target_w}x{target_h} @ {scale}x)",
            })

        except Exception as err:
            rows.append({
                "Row": f"{index:03d}",
                "SourceFile": payload.name,
                "CompositionId": "N/A",
                "EntryFile": "N/A",
                "Status": "invalid_payload",
                "Notes": f"Failed to extract composition: {err}",
            })

    root_lines = [
        'import React from "react";',
        'import "./index.css";',
        *registrations,
        "",
        "export const RemotionRoot: React.FC = () => (",
        "  <>",
    ]
    for idx in range(1, valid_count + 1):
        alias = f"Video{idx:03d}"
        root_lines.append(f"    <{alias}.Root />")
    root_lines.extend(["  </>", ");", ""])
    (PROJECT_DIR / "src" / "Root.tsx").write_text("\n".join(root_lines), encoding="utf-8", newline="\n")

    update_modal_render_jobs(modal_jobs)

    with STATUS_PATH.open("w", newline="", encoding="utf-8") as status_file:
        writer = csv.DictWriter(status_file, fieldnames=["Row", "SourceFile", "CompositionId", "EntryFile", "Status", "Notes"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Processed {len(rows)} payloads: {valid_count} prepared, {len(rows) - valid_count} invalid. CSV saved to {STATUS_PATH}")


if __name__ == "__main__":
    main()
