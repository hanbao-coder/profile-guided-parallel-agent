from __future__ import annotations

import ast
from pathlib import Path

from .models import StaticAnalysis


class _Visitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.functions: set[str] = set()
        self.calls: set[str] = set()
        self.reads: set[str] = set()
        self.writes: set[str] = set()
        self.globals: set[str] = set()
        self.loops = 0
        self.hazards: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.functions.add(node.name)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            self.calls.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            self.calls.add(node.func.attr)
            if node.func.attr in {"append", "extend", "update", "write", "writelines"}:
                self.hazards.add(f"shared_mutation:{node.func.attr}")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self.reads.add(node.id)
        elif isinstance(node.ctx, (ast.Store, ast.Del)):
            self.writes.add(node.id)

    def visit_Global(self, node: ast.Global) -> None:
        self.globals.update(node.names)
        self.hazards.add("global_state")

    def visit_For(self, node: ast.For) -> None:
        self.loops += 1
        self._inspect_loop(node)
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self.loops += 1
        self.hazards.add("while_loop_requires_review")
        self.generic_visit(node)

    def _inspect_loop(self, node: ast.For) -> None:
        loop_reads: set[str] = set()
        loop_writes: set[str] = set()
        indexed_reads: set[str] = set()
        indexed_writes: set[str] = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Name):
                if isinstance(child.ctx, ast.Load):
                    loop_reads.add(child.id)
                elif isinstance(child.ctx, ast.Store):
                    loop_writes.add(child.id)
            if isinstance(child, ast.AugAssign):
                self.hazards.add("reduction_or_loop_carried_dependency")
            if isinstance(child, ast.Subscript) and isinstance(child.value, ast.Name):
                if isinstance(child.ctx, ast.Load):
                    indexed_reads.add(child.value.id)
                elif isinstance(child.ctx, ast.Store):
                    indexed_writes.add(child.value.id)
        if indexed_reads & indexed_writes:
            names = ",".join(sorted(indexed_reads & indexed_writes))
            self.hazards.add(f"indexed_loop_carried_dependency:{names}")
        carried = (loop_reads & loop_writes) - {
            n.id for n in ast.walk(node.target) if isinstance(n, ast.Name)
        }
        if carried:
            self.hazards.add("possible_loop_carried_dependency:" + ",".join(sorted(carried)))


def analyze_source(source: str, source_name: str = "<memory>") -> StaticAnalysis:
    tree = ast.parse(source, filename=source_name)
    visitor = _Visitor()
    visitor.visit(tree)
    hard_hazards = {
        "global_state",
        "while_loop_requires_review",
    }
    parallelizable = visitor.loops > 0 and not any(
        h in hard_hazards
        or h.startswith("possible_loop_carried_dependency")
        or h.startswith("indexed_loop_carried_dependency")
        for h in visitor.hazards
    )
    return StaticAnalysis(
        source=source_name,
        functions=sorted(visitor.functions),
        calls=sorted(visitor.calls),
        loops=visitor.loops,
        read_names=sorted(visitor.reads),
        written_names=sorted(visitor.writes),
        global_names=sorted(visitor.globals),
        hazards=sorted(visitor.hazards),
        parallelizable=parallelizable,
    )


def analyze_file(path: str | Path) -> StaticAnalysis:
    file_path = Path(path)
    return analyze_source(file_path.read_text(encoding="utf-8"), str(file_path))
