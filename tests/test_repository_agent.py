from __future__ import annotations

from pathlib import Path
import json

import pytest
import parallel_agent.repository_agent as repository_agent

from parallel_agent.repository_agent import (
    ControlledCommand,
    RepositoryAgentConfig,
    RepositoryAgentError,
    RepositoryAgentSession,
    _safe_path,
    _search,
    _replace_with_context,
)


def _command(tmp_path: Path) -> ControlledCommand:
    return ControlledCommand(
        name="noop",
        argv=("python", "-c", "print('ok')"),
        timeout_seconds=5,
        cwd=tmp_path,
        env={},
    )


def _session(
    tmp_path: Path,
    *,
    edit_mode: str = "legacy",
    contract_mode: bool = False,
    performance_feedback_mode: bool = False,
) -> RepositoryAgentSession:
    command = _command(tmp_path)
    return RepositoryAgentSession(
        RepositoryAgentConfig(
            project_id="demo",
            repository_root=tmp_path,
            run_dir=tmp_path / "run",
            model="unused",
            flash_model="unused-flash",
            base_url="https://example.invalid",
            api_key="local-test-key",
            test_command=command,
            benchmark_command=command,
            edit_mode=edit_mode,
            contract_mode=contract_mode,
            performance_feedback_mode=performance_feedback_mode,
        )
    )


def test_safe_path_rejects_escape(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("value = 1\n", encoding="utf-8")
    assert _safe_path(tmp_path, "main.py") == tmp_path / "main.py"
    with pytest.raises(RepositoryAgentError, match="escapes repository"):
        _safe_path(tmp_path, "../outside.py")


def test_search_returns_file_and_line(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text(
        "def serial_loop():\n    return 1\n",
        encoding="utf-8",
    )
    assert _search(tmp_path, "serial_loop") == [
        {"path": "main.py", "line": 1, "text": "def serial_loop():"}
    ]


def test_apply_edit_requires_unique_exact_text(tmp_path: Path) -> None:
    source = tmp_path / "main.py"
    source.write_text("value = 1\n", encoding="utf-8")
    session = _session(tmp_path)
    result = session._apply_edits(
        {
            "edits": [
                {
                    "path": "main.py",
                    "old": "value = 1",
                    "new": "value = 2",
                }
            ]
        }
    )
    assert result["ok"] is True
    assert source.read_text(encoding="utf-8") == "value = 2\n"
    with pytest.raises(RepositoryAgentError, match="context edit"):
        session._apply_edits(
            {
                "edits": [
                    {
                        "path": "main.py",
                        "old": "missing",
                        "new": "other",
                    }
                ]
            }
        )


def test_multiple_edits_to_one_file_are_chained(tmp_path: Path) -> None:
    source = tmp_path / "main.py"
    source.write_text("first = 1\nsecond = 2\n", encoding="utf-8")
    result = _session(tmp_path)._apply_edits(
        {
            "edits": [
                {"path": "main.py", "old": "first = 1", "new": "first = 10"},
                {"path": "main.py", "old": "second = 2", "new": "second = 20"},
            ]
        }
    )
    assert result["files"] == ["main.py"]
    assert source.read_text(encoding="utf-8") == "first = 10\nsecond = 20\n"


def test_read_lines_returns_requested_numbered_range(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text(
        "line one\nline two\nline three\n",
        encoding="utf-8",
    )
    result = _session(tmp_path)._read_lines(
        {"path": "main.py", "start": 2, "end": 3}
    )
    assert result["content"] == "line two\nline three"
    assert result["numbered_content"] == "2: line two\n3: line three"
    assert len(result["anchor_sha256"]) == 64


def test_anchored_edit_requires_a_previously_read_current_range(
    tmp_path: Path,
) -> None:
    source = tmp_path / "main.py"
    source.write_text("first = 1\nsecond = 2\n", encoding="utf-8")
    session = _session(tmp_path, edit_mode="anchored")
    observed = session._read_lines(
        {"path": "main.py", "start": 1, "end": 1}
    )

    result = session._apply_edits(
        {
            "edits": [
                {
                    "path": "main.py",
                    "start": 1,
                    "end": 1,
                    "anchor_sha256": observed["anchor_sha256"],
                    "new": "first = 10",
                }
            ]
        }
    )

    assert result["matches"][0]["mode"] == "anchored"
    assert source.read_text(encoding="utf-8") == "first = 10\nsecond = 2\n"
    with pytest.raises(RepositoryAgentError, match="anchor was not returned"):
        session._apply_edits(
            {
                "edits": [
                    {
                        "path": "main.py",
                        "start": 1,
                        "end": 1,
                        "anchor_sha256": observed["anchor_sha256"],
                        "new": "first = 20",
                    }
                ]
            }
        )


def test_anchored_edit_rejects_source_changed_since_read(
    tmp_path: Path,
) -> None:
    source = tmp_path / "main.py"
    source.write_text("value = 1\n", encoding="utf-8")
    session = _session(tmp_path, edit_mode="anchored")
    observed = session._read_lines(
        {"path": "main.py", "start": 1, "end": 1}
    )
    source.write_text("value = 2\n", encoding="utf-8")

    with pytest.raises(RepositoryAgentError, match="source changed"):
        session._apply_edits(
            {
                "edits": [
                    {
                        "path": "main.py",
                        "start": 1,
                        "end": 1,
                        "anchor_sha256": observed["anchor_sha256"],
                        "new": "value = 3",
                    }
                ]
            }
        )


def test_read_line_anchor_is_retained_in_working_memory(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("value = 1\n", encoding="utf-8")
    session = _session(tmp_path, edit_mode="anchored")
    action = {
        "action": "read_lines",
        "path": "main.py",
        "start": 1,
        "end": 1,
    }
    observation = session._read_lines(action)

    session._update_working_memory(action, observation)

    evidence = next(iter(session.working_files.values()))
    assert observation["anchor_sha256"] in evidence
    assert '"start": 1' in evidence


def test_anchored_mode_reserves_one_exploration_for_read_lines(
    tmp_path: Path,
) -> None:
    (tmp_path / "main.py").write_text("value = 1\n", encoding="utf-8")
    session = _session(tmp_path, edit_mode="anchored")
    object.__setattr__(
        session,
        "exploration_actions",
        session.config.max_exploration_actions - 1,
    )

    with pytest.raises(RepositoryAgentError, match="reserved for read_lines"):
        session._execute_action(
            {
                "action": "read_files",
                "paths": ["main.py"],
            }
        )

    observation, finished = session._execute_action(
        {
            "action": "read_lines",
            "path": "main.py",
            "start": 1,
            "end": 1,
        }
    )
    assert observation["ok"] is True
    assert finished is False


def test_contract_mode_requires_grounded_contract_before_edit(
    tmp_path: Path,
) -> None:
    source = tmp_path / "main.py"
    source.write_text("value = 1\n", encoding="utf-8")
    session = _session(
        tmp_path,
        edit_mode="anchored",
        contract_mode=True,
    )
    observed = session._read_lines(
        {"path": "main.py", "start": 1, "end": 1}
    )
    edit = {
        "action": "apply_edits",
        "edits": [
            {
                "path": "main.py",
                "start": 1,
                "end": 1,
                "anchor_sha256": observed["anchor_sha256"],
                "new": "value = 2",
            }
        ],
    }

    with pytest.raises(RepositoryAgentError, match="contract before editing"):
        session._apply_edits(edit)

    contract = {
        "target": "main.value",
        "worker_inputs": ["value"],
        "worker_outputs": ["updated value"],
        "shared_or_dynamic_state": ["none observed"],
        "ordering": "single result preserves input order",
        "error_and_exit_behavior": "propagate the original exception",
        "serialization_risks": ["integer input is serializable"],
        "backend": "process",
        "backend_rationale": "CPU-bound work can bypass the GIL",
        "fallback_conditions": ["keep serial execution for one input"],
        "evidence": [
            {
                "path": "main.py",
                "start": 1,
                "end": 1,
                "anchor_sha256": observed["anchor_sha256"],
            }
        ],
    }
    result = session._declare_contract(
        {"action": "declare_contract", "contract": contract}
    )
    assert result["ok"] is True
    assert session.parallel_contract == contract
    assert (session.run_dir / "parallelization-contract.json").is_file()

    session._apply_edits(edit)
    assert source.read_text(encoding="utf-8") == "value = 2\n"


def test_contract_rejects_ungrounded_evidence(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("value = 1\n", encoding="utf-8")
    session = _session(
        tmp_path,
        edit_mode="anchored",
        contract_mode=True,
    )
    contract = {
        "target": "main.value",
        "worker_inputs": ["value"],
        "worker_outputs": ["updated value"],
        "shared_or_dynamic_state": ["none observed"],
        "ordering": "preserve order",
        "error_and_exit_behavior": "preserve errors",
        "serialization_risks": ["none observed"],
        "backend": "process",
        "backend_rationale": "CPU-bound",
        "fallback_conditions": ["small input"],
        "evidence": [
            {
                "path": "main.py",
                "start": 1,
                "end": 1,
                "anchor_sha256": "0" * 64,
            }
        ],
    }

    with pytest.raises(RepositoryAgentError, match="not returned"):
        session._declare_contract(
            {"action": "declare_contract", "contract": contract}
        )


def test_performance_feedback_accepts_only_correct_end_to_end_gain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "main.py").write_text("value = 1\n", encoding="utf-8")
    session = _session(tmp_path, performance_feedback_mode=True)
    session.project_context = {
        "serial_median_seconds": 10.0,
        "baseline_output_hash": "expected",
    }
    results = iter(
        [
            {
                "name": "tests",
                "returncode": 0,
                "elapsed_seconds": 1.0,
                "timed_out": False,
                "stdout": "all tests passed",
                "stderr": "",
            },
            {
                "name": "benchmark",
                "returncode": 0,
                "elapsed_seconds": 8.0,
                "timed_out": False,
                "stdout": json.dumps(
                    {
                        "median_seconds": 8.0,
                        "timings_seconds": [8.0],
                        "output_hashes": ["expected"],
                        "stable_output": True,
                    }
                ),
                "stderr": "",
            },
        ]
    )
    monkeypatch.setattr(repository_agent, "run_controlled", lambda command: next(results))

    evaluation = session._evaluate_candidate()

    assert evaluation["status"] == "effective_end_to_end_gain"
    assert evaluation["speedup"] == pytest.approx(1.25)


def test_feedback_finish_rejects_slow_candidate_then_allows_safe_fallback(
    tmp_path: Path,
) -> None:
    source = tmp_path / "main.py"
    source.write_text("value = 1\n", encoding="utf-8")
    session = _session(tmp_path, performance_feedback_mode=True)
    session._apply_edits(
        {
            "edits": [
                {
                    "path": "main.py",
                    "old": "value = 1",
                    "new": "value = 2",
                }
            ]
        }
    )
    session.last_candidate_evaluation = {
        "status": "end_to_end_performance_regression"
    }

    with pytest.raises(RepositoryAgentError, match="finish rejected"):
        session._execute_action({"action": "finish"})

    with pytest.raises(RepositoryAgentError, match="at least one repair"):
        session._execute_action(
            {"action": "abandon_candidate", "reason": "measured slower than serial"}
        )

    session.edit_rounds = 2
    fallback, finished = session._execute_action(
        {"action": "abandon_candidate", "reason": "measured slower than serial"}
    )
    assert finished is False
    assert fallback["status"] == "safe_serial_fallback"
    assert source.read_text(encoding="utf-8") == "value = 1\n"
    _, finished = session._execute_action({"action": "finish"})
    assert finished is True


def test_feedback_rejects_fast_but_wrong_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "main.py").write_text("value = 1\n", encoding="utf-8")
    session = _session(tmp_path, performance_feedback_mode=True)
    session.project_context = {
        "serial_median_seconds": 10.0,
        "baseline_output_hash": "expected",
    }
    results = iter(
        [
            {
                "name": "tests",
                "returncode": 0,
                "elapsed_seconds": 1.0,
                "timed_out": False,
                "stdout": "all tests passed",
                "stderr": "",
            },
            {
                "name": "benchmark",
                "returncode": 0,
                "elapsed_seconds": 0.01,
                "timed_out": False,
                "stdout": json.dumps(
                    {
                        "median_seconds": 0.01,
                        "timings_seconds": [0.01],
                        "output_hashes": ["wrong"],
                        "stable_output": True,
                    }
                ),
                "stderr": "",
            },
        ]
    )
    monkeypatch.setattr(repository_agent, "run_controlled", lambda command: next(results))

    evaluation = session._evaluate_candidate()

    assert evaluation["status"] == "integration_or_output_failure"
    assert evaluation["expected_output_hash"] == "expected"


def test_feedback_mode_allows_focused_read_after_edit(
    tmp_path: Path,
) -> None:
    source = tmp_path / "main.py"
    source.write_text("value = 1\n", encoding="utf-8")
    session = _session(tmp_path, performance_feedback_mode=True)
    session.edit_rounds = 1
    session.exploration_actions = session.config.max_exploration_actions

    result, finished = session._execute_action(
        {
            "action": "read_lines",
            "path": "main.py",
            "start": 1,
            "end": 1,
        }
    )

    assert finished is False
    assert result["content"] == "value = 1"
    assert session.repair_read_actions == 1
    assert session.repair_anchor_ready is True
    assert session.exploration_actions == session.config.max_exploration_actions

    with pytest.raises(RepositoryAgentError, match="already available"):
        session._execute_action(
            {
                "action": "read_lines",
                "path": "main.py",
                "start": 1,
                "end": 1,
            }
        )


def test_feedback_mode_automatically_restores_rejected_candidate_at_turn_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "main.py"
    source.write_text("value = 2\n", encoding="utf-8")
    session = _session(tmp_path, performance_feedback_mode=True)
    session.original_contents[source] = "value = 1\n"
    session.edit_rounds = 2
    session.last_candidate_evaluation = {
        "status": "end_to_end_performance_regression"
    }
    monkeypatch.setattr(
        session,
        "_call_model",
        lambda: {"action": "finish", "reason": "incorrect early finish"},
    )

    result = session.run(
        {
            "serial_median_seconds": 10.0,
            "baseline_output_hash": "expected",
        }
    )

    assert result["finished"] is True
    assert result["events"][-1]["action"]["action"] == "automatic_safe_fallback"
    assert source.read_text(encoding="utf-8") == "value = 1\n"


def test_feedback_mode_returns_fresh_anchor_after_edit(
    tmp_path: Path,
) -> None:
    source = tmp_path / "main.py"
    source.write_text("first = 1\nsecond = 2\n", encoding="utf-8")
    session = _session(
        tmp_path,
        edit_mode="anchored",
        performance_feedback_mode=True,
    )
    initial = session._read_lines({"path": "main.py", "start": 1, "end": 2})
    edit_result = session._apply_edits(
        {
            "edits": [
                {
                    "path": "main.py",
                    "start": 1,
                    "end": 2,
                    "anchor_sha256": initial["anchor_sha256"],
                    "new": "first = 10\nsecond = 20",
                }
            ]
        }
    )

    anchors = session._fresh_repair_anchors(edit_result)

    assert len(anchors) == 1
    assert anchors[0]["content"] == "first = 10\nsecond = 20"
    assert (
        "main.py",
        1,
        2,
        anchors[0]["anchor_sha256"],
    ) in session.read_anchors


def test_read_files_returns_subset_that_fits_budget(tmp_path: Path) -> None:
    (tmp_path / "one.py").write_text("a" * 30, encoding="utf-8")
    (tmp_path / "two.py").write_text("b" * 30, encoding="utf-8")
    session = _session(tmp_path)
    object.__setattr__(session.config, "max_total_read_characters", 40)
    result = session._read_files({"paths": ["one.py", "two.py"]})
    assert [item["path"] for item in result["files"]] == ["one.py"]
    assert result["skipped_paths"] == ["two.py"]


def test_context_edit_accepts_unique_anchored_block() -> None:
    content = "before\n\ndef work():\n    value = 1\n    extra = 2\n    return value\n\nafter\n"
    old = "def work():\n    value = 1\n    return value"
    new = "def work():\n    return 10"
    updated, mode, similarity = _replace_with_context(content, old, new)
    assert mode == "context"
    assert similarity >= 0.80
    assert "def work():\n    return 10\n" in updated
    assert "extra = 2" not in updated


def test_context_edit_rejects_ambiguous_anchors() -> None:
    content = (
        "def work():\n    value = 1\n    return value\n\n"
        "def work():\n    value = 2\n    return value\n"
    )
    old = "def work():\n    value = 3\n    return value"
    with pytest.raises(RepositoryAgentError, match="ambiguous"):
        _replace_with_context(content, old, "def work():\n    return 4")
