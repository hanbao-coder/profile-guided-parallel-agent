from scripts.verify_radon_manual_reference import _compact_baseline


def test_compact_baseline_removes_large_and_machine_specific_fields() -> None:
    compact = _compact_baseline(
        {
            "median_seconds": 1.2,
            "canonical_output": {"large": True},
            "input_root": "C:/machine/path",
            "python": "version",
        }
    )

    assert compact == {"median_seconds": 1.2}
