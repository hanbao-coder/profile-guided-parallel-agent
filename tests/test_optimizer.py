from parallel_agent.optimizer import (
    BackendCalibration,
    choose_execution_plan,
    worker_candidates,
)


def test_worker_candidates_include_powers_of_two_and_limit() -> None:
    assert worker_candidates(6) == [1, 2, 4, 6]


def test_short_job_falls_back_to_serial() -> None:
    plan = choose_execution_plan(
        item_count=10,
        item_runtime_seconds=0.001,
        calibrations={
            2: BackendCalibration(2, 0.1, 0.001),
            4: BackendCalibration(4, 0.1, 0.001),
        },
    )
    assert plan.selected_mode == "serial_fallback"
    assert plan.workers == 1


def test_long_job_selects_parallel_plan() -> None:
    plan = choose_execution_plan(
        item_count=100,
        item_runtime_seconds=0.1,
        calibrations={
            2: BackendCalibration(2, 0.1, 0.001),
            4: BackendCalibration(4, 0.15, 0.001),
        },
    )
    assert plan.selected_mode == "optimized"
    assert plan.workers == 4
    assert plan.chunks in {4, 8, 16, 32}


def test_communication_cost_can_trigger_fallback() -> None:
    plan = choose_execution_plan(
        item_count=100,
        item_runtime_seconds=0.001,
        calibrations={4: BackendCalibration(4, 0.01, 0.0001)},
        serialization_seconds=1.0,
    )
    assert plan.selected_mode == "serial_fallback"


def test_high_runtime_variation_keeps_more_chunks_for_balancing() -> None:
    calibrations = {4: BackendCalibration(4, 0.0, 0.0001)}
    uniform = choose_execution_plan(
        item_count=64,
        item_runtime_seconds=0.01,
        calibrations=calibrations,
    )
    imbalanced = choose_execution_plan(
        item_count=64,
        item_runtime_seconds=0.01,
        item_runtime_coefficient_of_variation=1.5,
        calibrations=calibrations,
    )
    assert uniform.selected_mode == "optimized"
    assert imbalanced.selected_mode == "optimized"
    assert imbalanced.chunks > uniform.chunks
    assert imbalanced.predicted_imbalance_factor > 1.0
