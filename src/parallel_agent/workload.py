from __future__ import annotations

from typing import Any, Protocol, Sequence


class Workload(Protocol):
    NAME: str

    def make_input(self, size: int, seed: int) -> Sequence[Any]: ...

    def unit(self, item: Any) -> Any: ...

    def combine(self, values: Sequence[Any]) -> Any: ...

    def equivalent(self, left: Any, right: Any) -> bool: ...

