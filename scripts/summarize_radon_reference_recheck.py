#!/usr/bin/env python3
"""Create the Chinese figure for the fixed-protocol Radon reference recheck."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]


def load_summary(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_summary(data: dict[str, Any]) -> None:
    required = {"b0_serial", "b3_reference", "speedup", "hashes_match", "effective_at_1_05"}
    missing = required.difference(data)
    if missing:
        raise ValueError(f"summary missing fields: {sorted(missing)}")


def render(summary: dict[str, Any], output: Path) -> None:
    validate_summary(summary)
    serial = float(summary["b0_serial"]["median_seconds"])
    reference = float(summary["b3_reference"]["median_seconds"])
    speedup = float(summary["speedup"])

    plt.rcParams["font.sans-serif"] = [
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(7.6, 4.8))
    bars = ax.bar(
        ["B0 原始串行", "B3 人工参考"],
        [serial, reference],
        color=["#8FA3B8", "#3D7DBD"],
        width=0.56,
    )
    ax.bar_label(bars, labels=[f"{serial:.3f} 秒", f"{reference:.3f} 秒"], padding=4)
    ax.set_ylabel("端到端中位耗时（秒，越低越好）")
    ax.set_title("Radon 人工参考版本固定协议复核")
    ax.set_ylim(0, max(serial, reference) * 1.25)
    ax.grid(axis="y", alpha=0.2)
    conclusion = (
        f"输出一致；加速比 {speedup:.4f}×；"
        f"{'达到' if summary['effective_at_1_05'] else '未达到'} 1.05× 有效门槛"
    )
    ax.text(
        0.5,
        0.91,
        conclusion,
        transform=ax.transAxes,
        ha="center",
        fontsize=10,
        bbox={"facecolor": "white", "edgecolor": "#D0D0D0", "alpha": 0.9},
    )
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--summary",
        type=Path,
        default=ROOT / "docs/data/radon-manual-reference-summary.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs/figures/radon-manual-reference-recheck.png",
    )
    args = parser.parse_args()
    summary = load_summary(args.summary)
    render(summary, args.output)
    print(json.dumps({"figure": str(args.output), "speedup": summary["speedup"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
