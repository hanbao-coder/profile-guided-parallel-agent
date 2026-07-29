from parallel_agent.analyzer import analyze_source


def test_independent_loop_is_candidate() -> None:
    source = """
def transform(values):
    result = []
    for value in values:
        result.append(value * value)
    return result
"""
    result = analyze_source(source)
    assert result.loops == 1
    assert result.parallelizable
    assert "shared_mutation:append" in result.hazards


def test_loop_carried_dependency_is_flagged() -> None:
    source = """
def prefix(values):
    out = [0] * len(values)
    for i, value in enumerate(values):
        out[i] = value if i == 0 else out[i - 1] + value
    return out
"""
    result = analyze_source(source)
    assert result.loops == 1
    assert "indexed_loop_carried_dependency:out" in result.hazards
    assert not result.parallelizable
