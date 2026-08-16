#!/usr/bin/env python3
"""Build measured Worker-boundary cards for the two M8 scikit-learn tasks."""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
from pathlib import Path
from typing import Any

from parallel_agent.boundary_evidence import probe_backends, probe_payload_plan


def _binning_worker(item: tuple[Any, int]):
    from sklearn.ensemble._hist_gradient_boosting.binning import (
        _find_binning_thresholds,
    )

    column, max_bins = item
    return _find_binning_thresholds(column, max_bins)


def _column_worker(frame):
    return frame.squeeze(axis=1).apply(sum).to_numpy().reshape(-1, 1)


def _full_frame_worker(item: tuple[Any, str]):
    frame, column = item
    return _column_worker(frame[[column]])


def _base_environment() -> dict[str, object]:
    import joblib
    import numpy as np
    import sklearn

    payload: dict[str, object] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "logical_cpus": os.cpu_count(),
        "numpy": np.__version__,
        "joblib": joblib.__version__,
        "scikit_learn": sklearn.__version__,
    }
    try:
        import pandas as pd

        payload["pandas"] = pd.__version__
    except ImportError:
        pass
    return payload


def _binning_card(*, workers: int, repeats: int) -> dict[str, object]:
    from sklearn.datasets import make_classification

    samples = 200_000
    features = 20
    max_bins = 255
    matrix, _ = make_classification(
        n_samples=samples,
        n_features=features,
        random_state=20260816,
    )
    projected_items = [
        (matrix[:, feature], max_bins) for feature in range(features)
    ]
    full_once = probe_payload_plan([matrix], repeats=repeats)
    projected = probe_payload_plan(projected_items, repeats=repeats)
    full_per_task_bytes = int(full_once["total_bytes"]) * features
    projected_bytes = int(projected["total_bytes"])
    return {
        "schema_version": 1,
        "task": "scikit-learn__scikit-learn-28064",
        "candidate_region": "_BinMapper.fit 中逐特征计算分箱阈值的循环",
        "worker_unit": "为一个数值特征计算分箱阈值",
        "worker_inputs": ["一个特征列", "max_bins"],
        "worker_outputs": ["该特征的阈值数组"],
        "state_risks": [
            "结果完成顺序可能变化，必须按原特征编号放回",
            "类别特征仍需保留原来的单独处理逻辑",
            "必须继续遵守现有self.n_threads设置，不能把实验中的4个Worker写死到项目代码中",
        ],
        "payload_evidence": {
            "full_matrix_repeated_for_each_task_bytes": full_per_task_bytes,
            "projected_feature_tasks_total_bytes": projected_bytes,
            "full_to_projected_ratio": full_per_task_bytes / projected_bytes,
            "note": "进程传输代理；线程共享内存时不等于实际传输量。",
        },
        "backend_evidence": probe_backends(
            _binning_worker,
            projected_items,
            workers=workers,
            repeats=repeats,
            include_process=True,
        ),
        "ordering_and_merge": "保留长度为n_features的结果槽，按feature index写回。",
        "evidence_limit": "代表性输入上的小规模后端试验，不是最终补丁性能。",
        "environment": _base_environment(),
    }


def _column_transformer_card(
    *, rows: int, columns: int, workers: int, repeats: int
) -> dict[str, object]:
    import pandas as pd

    generator = random.Random(20260816)
    frame = pd.DataFrame(
        {
            str(column): [
                [generator.random() for _ in range(generator.randint(1, 5))]
                for _ in range(rows)
            ]
            for column in range(columns)
        }
    )
    projected_items = [frame[[str(column)]] for column in range(columns)]
    full_items = [(frame, str(column)) for column in range(columns)]
    full_once = probe_payload_plan([frame], repeats=repeats)
    projected = probe_payload_plan(projected_items, repeats=repeats)
    full_per_task_bytes = int(full_once["total_bytes"]) * columns
    projected_bytes = int(projected["total_bytes"])
    return {
        "schema_version": 1,
        "task": "scikit-learn__scikit-learn-29330",
        "candidate_region": "ColumnTransformer._call_func_on_transformers 的并行任务提交",
        "worker_unit": "对一个transformer所需的列执行fit_transform或transform",
        "worker_inputs": ["transformer", "该transformer需要的列", "y", "参数"],
        "worker_outputs": ["转换后的列块"],
        "state_risks": [
            "对象类型列不能依赖joblib自动memmap共享",
            "完整DataFrame若作为每个任务参数，会被重复序列化",
        ],
        "payload_evidence": {
            "probe_rows": rows,
            "task_count": columns,
            "full_dataframe_repeated_for_each_task_bytes": full_per_task_bytes,
            "presliced_columns_total_bytes": projected_bytes,
            "full_to_projected_ratio": full_per_task_bytes / projected_bytes,
        },
        "backend_evidence": {
            "full_input_boundary": probe_backends(
                _full_frame_worker,
                full_items,
                workers=workers,
                repeats=repeats,
                include_process=True,
            ),
            "projected_input_boundary": probe_backends(
                _column_worker,
                projected_items,
                workers=workers,
                repeats=repeats,
                include_process=True,
            ),
        },
        "ordering_and_merge": "保持transformers原顺序，继续由ColumnTransformer合并结果。",
        "evidence_limit": "边界试验使用代表性子样本；最终结论仍由10万行端到端基准决定。",
        "environment": _base_environment(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=("28064", "29330"), required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--rows", type=int, default=10_000)
    parser.add_argument("--columns", type=int, default=40)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.task == "28064":
        card = _binning_card(workers=args.workers, repeats=args.repeats)
    else:
        card = _column_transformer_card(
            rows=args.rows,
            columns=args.columns,
            workers=args.workers,
            repeats=args.repeats,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(card, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
