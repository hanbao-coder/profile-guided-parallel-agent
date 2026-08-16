#!/usr/bin/env python3
"""Copy candidate Python sources over an isolated scikit-learn installation."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


def sync_python_tree(source: Path, destination: Path) -> dict[str, object]:
    if not source.is_dir() or not destination.is_dir():
        raise FileNotFoundError(f"invalid sync roots: {source} -> {destination}")
    copied = 0
    digest = hashlib.sha256()
    for source_path in sorted(source.rglob("*.py")):
        relative = source_path.relative_to(source)
        destination_path = destination / relative
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)
        data = source_path.read_bytes()
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(data)
        copied += 1
    return {
        "source": str(source),
        "destination": str(destination),
        "python_files_copied": copied,
        "source_tree_sha256": digest.hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            sync_python_tree(args.source, args.destination),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
