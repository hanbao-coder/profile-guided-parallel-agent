from pathlib import Path

import yaml

from parallel_agent.suite import run_suite


ROOT = Path(__file__).resolve().parents[1]


def test_suite_writes_csv_and_manifest(tmp_path: Path) -> None:
    config = {
        "benchmarks": {
            "prime_count": {
                "path": "benchmarks/prime_count/workload.py",
                "small": 1,
                "large": 1,
            }
        }
    }
    config_path = ROOT / "work" / "test-suite.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    result = run_suite(
        config_path,
        scale="small",
        workers=1,
        repeats=1,
        warmups=0,
        seed=42,
        backend="multiprocessing",
        output_dir=tmp_path,
        randomize_order=True,
    )
    assert result["manifest"]["benchmarks"] == ["prime_count"]
    assert result["manifest"]["ray_address"] is None
    assert (tmp_path / "suite_small.csv").exists()
    assert (tmp_path / "suite_small_manifest.json").exists()
