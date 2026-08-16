from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SYNC = _load("sync_sklearn_candidate", ROOT / "scripts" / "sync_sklearn_candidate.py")
EVALUATOR = _load(
    "evaluate_sklearn_candidate", ROOT / "scripts" / "evaluate_sklearn_candidate.py"
)


def test_sync_copies_only_python_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    (source / "nested").mkdir(parents=True)
    destination.mkdir()
    (source / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (source / "nested" / "child.py").write_text("VALUE = 2\n", encoding="utf-8")
    (source / "native.so").write_bytes(b"do-not-copy")

    result = SYNC.sync_python_tree(source, destination)

    assert result["python_files_copied"] == 2
    assert (destination / "module.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert (destination / "nested" / "child.py").is_file()
    assert not (destination / "native.so").exists()


def test_windows_path_is_converted_for_wsl() -> None:
    converted = EVALUATOR.windows_to_wsl_path(Path("D:/hustagent/trial"))

    assert converted.lower() == "/mnt/d/hustagent/trial"


def test_each_public_task_registers_project_style_files() -> None:
    assert EVALUATOR.TASKS["28064"]["style_files"] == (
        "ensemble/_hist_gradient_boosting/binning.py",
    )
    assert "pipeline.py" in EVALUATOR.TASKS["29330"]["style_files"]
