from __future__ import annotations

from pathlib import Path

import pytest

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
