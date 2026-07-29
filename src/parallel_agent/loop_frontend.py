from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class LoopNormalizationError(ValueError):
    """Raised when a serial loop is outside the conservative frontend."""


@dataclass(frozen=True)
class LoopNormalization:
    schema_version: str
    source_path: str
    source_sha256: str
    output_path: str
    output_sha256: str
    entry_function: str
    input_parameter: str
    item_variable: str
    results_variable: str
    unit_function: str
    combine_function: str
    input_factory: str
    equivalent_function: str
    parallel_pattern: str
    rationale: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _function_map(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }


def _body_without_docstring(
    function: ast.FunctionDef,
) -> list[ast.stmt]:
    body = list(function.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[1:]
    return body


def _single_name_argument(
    function: ast.FunctionDef,
) -> str | None:
    arguments = function.args
    if (
        len(arguments.posonlyargs) + len(arguments.args) != 1
        or arguments.vararg is not None
        or arguments.kwarg is not None
        or arguments.kwonlyargs
    ):
        return None
    positional = [*arguments.posonlyargs, *arguments.args]
    return positional[0].arg


def _match_entry(
    function: ast.FunctionDef,
) -> tuple[str, str, str, str, str] | None:
    input_parameter = _single_name_argument(function)
    body = _body_without_docstring(function)
    if input_parameter is None or len(body) != 3:
        return None

    initialize, loop, returned = body
    if (
        not isinstance(initialize, ast.Assign)
        or len(initialize.targets) != 1
        or not isinstance(initialize.targets[0], ast.Name)
        or not isinstance(initialize.value, ast.List)
        or initialize.value.elts
    ):
        return None
    results_variable = initialize.targets[0].id

    if (
        not isinstance(loop, ast.For)
        or loop.orelse
        or not isinstance(loop.target, ast.Name)
        or not isinstance(loop.iter, ast.Name)
        or loop.iter.id != input_parameter
        or len(loop.body) != 1
    ):
        return None
    item_variable = loop.target.id
    statement = loop.body[0]
    if not isinstance(statement, ast.Expr) or not isinstance(
        statement.value, ast.Call
    ):
        return None
    append_call = statement.value
    if (
        not isinstance(append_call.func, ast.Attribute)
        or append_call.func.attr != "append"
        or not isinstance(append_call.func.value, ast.Name)
        or append_call.func.value.id != results_variable
        or len(append_call.args) != 1
        or append_call.keywords
    ):
        return None
    unit_call = append_call.args[0]
    if (
        not isinstance(unit_call, ast.Call)
        or not isinstance(unit_call.func, ast.Name)
        or len(unit_call.args) != 1
        or unit_call.keywords
        or not isinstance(unit_call.args[0], ast.Name)
        or unit_call.args[0].id != item_variable
    ):
        return None
    unit_function = unit_call.func.id

    if not isinstance(returned, ast.Return) or not isinstance(
        returned.value, ast.Call
    ):
        return None
    combine_call = returned.value
    if (
        not isinstance(combine_call.func, ast.Name)
        or len(combine_call.args) != 1
        or combine_call.keywords
        or not isinstance(combine_call.args[0], ast.Name)
        or combine_call.args[0].id != results_variable
    ):
        return None
    combine_function = combine_call.func.id
    return (
        input_parameter,
        item_variable,
        results_variable,
        unit_function,
        combine_function,
    )


def _contains_global_state(function: ast.FunctionDef) -> bool:
    return any(
        isinstance(node, (ast.Global, ast.Nonlocal))
        for node in ast.walk(function)
    )


def analyze_serial_loop(
    source_path: str | Path,
    *,
    entry_function: str | None = None,
    input_factory: str = "make_input",
    equivalent_function: str = "equivalent",
) -> LoopNormalization:
    path = Path(source_path).resolve()
    source_bytes = path.read_bytes()
    source = source_bytes.decode("utf-8")
    tree = ast.parse(source, filename=str(path))
    functions = _function_map(tree)

    if entry_function:
        entry = functions.get(entry_function)
        if entry is None:
            raise LoopNormalizationError(
                f"Entry function '{entry_function}' was not found."
            )
        matched = _match_entry(entry)
        if matched is None:
            raise LoopNormalizationError(
                "The entry function is outside the supported independent "
                "map-then-combine loop pattern."
            )
    else:
        matches = [
            (function, matched)
            for function in functions.values()
            if (matched := _match_entry(function)) is not None
        ]
        if len(matches) != 1:
            raise LoopNormalizationError(
                "Expected exactly one supported serial loop; specify "
                "--entry when the source contains multiple candidates."
            )
        entry, matched = matches[0]

    (
        input_parameter,
        item_variable,
        results_variable,
        unit_function,
        combine_function,
    ) = matched
    required = {
        input_factory,
        equivalent_function,
        unit_function,
        combine_function,
    }
    missing = sorted(required - functions.keys())
    if missing:
        raise LoopNormalizationError(
            "The serial source is missing required helper functions: "
            + ", ".join(missing)
        )
    if _contains_global_state(functions[unit_function]):
        raise LoopNormalizationError(
            "The per-item function uses global/nonlocal state and is unsafe "
            "for independent task execution."
        )

    return LoopNormalization(
        schema_version="1.0",
        source_path=str(path),
        source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        output_path="",
        output_sha256="",
        entry_function=entry.name,
        input_parameter=input_parameter,
        item_variable=item_variable,
        results_variable=results_variable,
        unit_function=unit_function,
        combine_function=combine_function,
        input_factory=input_factory,
        equivalent_function=equivalent_function,
        parallel_pattern="independent_map_then_combine",
        rationale=[
            "The loop iterates directly over the entry input.",
            "Each iteration calls one per-item function and only appends its result.",
            "A separate combine function consumes the collected outputs.",
            "The per-item function contains no explicit global/nonlocal declaration.",
        ],
    )


_WRAPPER_TEMPLATE = '''\
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

NAME = {name!r}
ORIGINAL_SOURCE = {source_path!r}
EXPECTED_SOURCE_SHA256 = {source_sha256!r}


def _load_original():
    path = Path(ORIGINAL_SOURCE).resolve()
    actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_hash != EXPECTED_SOURCE_SHA256:
        raise RuntimeError(
            "Original serial source changed after normalization; regenerate "
            "the workload wrapper before executing experiments."
        )
    spec = importlib.util.spec_from_file_location(
        "normalized_serial_source", path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import original serial source: {{path}}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_source = _load_original()


def make_input(size: int, seed: int):
    return _source.{input_factory}(size, seed)


def unit(item):
    return _source.{unit_function}(item)


def combine(values):
    return _source.{combine_function}(values)


def equivalent(left, right):
    return _source.{equivalent_function}(left, right)
'''


def normalize_serial_loop(
    source_path: str | Path,
    *,
    output_path: str | Path,
    metadata_path: str | Path | None = None,
    entry_function: str | None = None,
    input_factory: str = "make_input",
    equivalent_function: str = "equivalent",
) -> LoopNormalization:
    analysis = analyze_serial_loop(
        source_path,
        entry_function=entry_function,
        input_factory=input_factory,
        equivalent_function=equivalent_function,
    )
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    wrapper = _WRAPPER_TEMPLATE.format(
        name=f"normalized_{Path(source_path).stem}",
        source_path=analysis.source_path,
        source_sha256=analysis.source_sha256,
        input_factory=analysis.input_factory,
        unit_function=analysis.unit_function,
        combine_function=analysis.combine_function,
        equivalent_function=analysis.equivalent_function,
    )
    output.write_text(wrapper, encoding="utf-8")
    normalized = LoopNormalization(
        **{
            **analysis.to_dict(),
            "output_path": str(output),
            "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        }
    )
    metadata = (
        Path(metadata_path).resolve()
        if metadata_path
        else output.with_suffix(".normalization.json")
    )
    metadata.parent.mkdir(parents=True, exist_ok=True)
    metadata.write_text(
        json.dumps(normalized.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return normalized


def load_verified_normalization(
    output_path: str | Path,
) -> LoopNormalization | None:
    output = Path(output_path).resolve()
    metadata = output.with_suffix(".normalization.json")
    if not metadata.exists():
        return None
    try:
        payload = json.loads(metadata.read_text(encoding="utf-8"))
        normalization = LoopNormalization(**payload)
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        raise LoopNormalizationError(
            f"Invalid normalization metadata: {exc}"
        ) from exc
    if Path(normalization.output_path).resolve() != output:
        raise LoopNormalizationError(
            "Normalization metadata points to a different wrapper."
        )
    actual_output_hash = hashlib.sha256(output.read_bytes()).hexdigest()
    if actual_output_hash != normalization.output_sha256:
        raise LoopNormalizationError(
            "Normalized wrapper changed after validation."
        )
    original = Path(normalization.source_path).resolve()
    if hashlib.sha256(original.read_bytes()).hexdigest() != (
        normalization.source_sha256
    ):
        raise LoopNormalizationError(
            "Original serial source changed after normalization."
        )
    repeated = analyze_serial_loop(
        original,
        entry_function=normalization.entry_function,
        input_factory=normalization.input_factory,
        equivalent_function=normalization.equivalent_function,
    )
    compared_fields = (
        "source_sha256",
        "entry_function",
        "input_parameter",
        "item_variable",
        "results_variable",
        "unit_function",
        "combine_function",
        "input_factory",
        "equivalent_function",
        "parallel_pattern",
    )
    if any(
        getattr(repeated, field) != getattr(normalization, field)
        for field in compared_fields
    ):
        raise LoopNormalizationError(
            "Normalization metadata no longer matches deterministic analysis."
        )
    return normalization
