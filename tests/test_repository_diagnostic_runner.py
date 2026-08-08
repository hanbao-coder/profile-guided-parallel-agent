from __future__ import annotations

from pathlib import Path
import sys

from scripts.run_repository_diagnostic import _import_preflight


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
