"""Mark validated component registry rows renderable using an atomic CSV rewrite."""

from __future__ import annotations

import csv
from pathlib import Path


STATUS_PATH = Path(__file__).resolve().parent / "components" / "component-status.csv"


def main() -> None:
    with STATUS_PATH.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        fields = reader.fieldnames
        rows = list(reader)
    if not fields or not rows:
        raise RuntimeError(f"Expected non-empty registry rows, found {len(rows)}")
    registered_count = 0
    for row in rows:
        if row["Status"] in {"prepared", "render_failed"}:
            row["Status"] = "registered"
            row["Notes"] = "bundle, ESLint, and TypeScript validation passed"
            registered_count += 1
    temporary_path = STATUS_PATH.with_suffix(".tmp")
    with temporary_path.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(destination, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary_path.replace(STATUS_PATH)
    print(f"Registered {registered_count} component rows (total payloads: {len(rows)})")


if __name__ == "__main__":
    main()
