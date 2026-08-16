from __future__ import annotations

from pathlib import Path
import sys

from scripts.run_repository_diagnostic import _import_preflight, _paired_formal_summary


def test_import_preflight_accepts_module_from_trial_src_layout(
    tmp_path: Path,
) -> None:
    package = tmp_path / "src" / "demo_package"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")

    result = _import_preflight(
        python=Path(sys.executable),
        module="demo_package",
        trial=tmp_path,
        import_subdir="src",
    )

    assert result["ok"] is True
    assert result["belongs_to_trial"] is True
    imported = Path(str(result["imported_path"]))
    assert imported.name == "__init__.py"
    assert imported.parent.name == "demo_package"


def test_import_preflight_rejects_module_resolved_outside_trial(
    tmp_path: Path,
) -> None:
    result = _import_preflight(
        python=Path(sys.executable),
        module="json",
        trial=tmp_path,
        import_subdir=".",
    )

    assert result["ok"] is False
    assert result["belongs_to_trial"] is False


def test_paired_formal_summary_brackets_candidate_with_two_baselines() -> None:
    def benchmark_result(seconds: float) -> dict[str, object]:
        return {"stdout": '{"median_seconds": ' + str(seconds) + "}"}

    summary = _paired_formal_summary(
        baseline_before=benchmark_result(10.0),
        candidate=benchmark_result(5.0),
        baseline_after=benchmark_result(12.0),
    )

    assert summary["paired_baseline_median_seconds"] == 11.0
    assert summary["speedup"] == 2.2
