from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_advisor_demo_is_offline_and_preserves_boundaries(tmp_path: Path) -> None:
    output_dir = tmp_path / "demo"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_advisor_demo.py"),
            "--output-dir",
            str(output_dir),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(
        (output_dir / "advisor_demo_summary.json").read_text(encoding="utf-8")
    )
    assert report["deepseek_api_called"] is False
    assert report["prefix_sum"]["parallelizable"] is False
    assert report["load_imbalance"]["all_holdout_outputs_match"] is True
    assert report["load_imbalance"]["selected_speedup"] > 1.0
    assert report["load_imbalance"]["fixed_speedup"] < 1.0
    assert report["tiny_tasks"]["decision"] == "fall_back_to_serial"
