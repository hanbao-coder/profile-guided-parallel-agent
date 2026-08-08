#!/usr/bin/env python3
"""Audit immutable local Agent runs and emit a compact hash manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
FORMAL_GROUPS = {
    "B1_ordinary_agent": {
        "root": Path("results/m5/corrected-b0"),
        "projects": ("radon", "vulture", "chardet", "mkdocs"),
    },
    "B2_full_method": {
        "root": Path("results/m5/corrected-final"),
        "projects": ("radon", "vulture", "chardet", "mkdocs"),
    },
    "A1_contract_only": {
        "root": Path("results/m6/ablation-contract-only"),
        "projects": ("mkdocs",),
    },
}
REQUIRED_FILES = (
    "import-preflight.json",
    "outcome.json",
    "agent/events.json",
    "agent/patch.diff",
    "agent/prompt.json",
    "agent/response.jsonl",
    "baseline/validation.json",
)
AUDITED_RESEARCH_ARTIFACTS = (
    Path("docs/data/m7-worker-boundary.json"),
    Path("docs/data/radon-manual-reference.patch"),
    Path("docs/data/radon-manual-reference-summary.json"),
    Path("docs/figures/m7-worker-boundary.png"),
    Path("docs/figures/radon-manual-reference-recheck.png"),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_json(path: Path) -> None:
    json.loads(path.read_text(encoding="utf-8"))


def _validate_jsonl(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"empty JSONL file: {path}")
    for index, line in enumerate(lines, start=1):
        try:
            json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL line {index}: {path}") from exc


def _audit_run(run_dir: Path, *, repository: Path) -> dict[str, object]:
    missing = [name for name in REQUIRED_FILES if not (run_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"{run_dir}: missing {', '.join(missing)}")
    files = sorted(path for path in run_dir.rglob("*") if path.is_file())
    for path in files:
        if path.suffix == ".json":
            _validate_json(path)
        elif path.suffix == ".jsonl":
            _validate_jsonl(path)
    outcome = json.loads((run_dir / "outcome.json").read_text(encoding="utf-8"))
    records = [
        {
            "path": path.relative_to(repository).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in files
    ]
    return {
        "project": outcome.get("project"),
        "run": run_dir.name,
        "status": outcome.get("status"),
        "patch_nonempty": outcome.get("patch_nonempty"),
        "file_count": len(records),
        "total_bytes": sum(record["bytes"] for record in records),
        "files": records,
    }


def audit_formal_groups(repository: Path) -> list[dict[str, object]]:
    groups = []
    for group_name, definition in FORMAL_GROUPS.items():
        group_runs = []
        group_root = repository / definition["root"]
        for project in definition["projects"]:
            for run_number in range(1, 4):
                run_dir = group_root / project / f"run-{run_number:02d}"
                record = _audit_run(run_dir, repository=repository)
                if record["project"] != project:
                    raise ValueError(
                        f"project mismatch in {run_dir}: {record['project']!r}"
                    )
                group_runs.append(record)
        groups.append(
            {
                "group": group_name,
                "root": definition["root"].as_posix(),
                "expected_runs": len(definition["projects"]) * 3,
                "audited_runs": len(group_runs),
                "runs": group_runs,
            }
        )
    return groups


def _find_exclusion_records(repository: Path) -> Iterable[dict[str, object]]:
    results = repository / "results"
    candidates = set(results.rglob("exclusion.json"))
    candidates.update(
        path
        for path in results.rglob("outcome.json")
        if any(part.startswith("excluded-") for part in path.parts)
    )
    for path in sorted(candidates):
        _validate_json(path)
        yield {
            "path": path.relative_to(repository).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }


def audit_research_artifacts(repository: Path) -> list[dict[str, object]]:
    records = []
    for relative in AUDITED_RESEARCH_ARTIFACTS:
        path = repository / relative
        if not path.is_file():
            raise FileNotFoundError(f"missing research artifact: {path}")
        if path.suffix == ".json":
            _validate_json(path)
        records.append(
            {
                "path": relative.as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs/data/research-evidence-manifest.json",
    )
    args = parser.parse_args()
    repository = args.repository.resolve()
    groups = audit_formal_groups(repository)
    formal_runs = sum(group["audited_runs"] for group in groups)
    evidence = {
        "schema_version": 1,
        "formal_run_count": formal_runs,
        "all_formal_runs_complete": formal_runs == 27,
        "required_files_per_run": list(REQUIRED_FILES),
        "groups": groups,
        "excluded_run_records": list(_find_exclusion_records(repository)),
        "additional_research_artifacts": audit_research_artifacts(repository),
        "note": (
            "The manifest proves which local raw files were audited. It does not "
            "embed model responses and cannot recreate them if the local results "
            "directory is deleted."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "formal_run_count": formal_runs,
                "all_formal_runs_complete": evidence["all_formal_runs_complete"],
                "excluded_record_count": len(evidence["excluded_run_records"]),
                "output": str(args.output.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if evidence["all_formal_runs_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
