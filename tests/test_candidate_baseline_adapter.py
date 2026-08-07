from pathlib import Path
import sys
from types import ModuleType

import scripts.run_candidate_baseline as adapter


def test_chardet_workload_uses_public_cli_entrypoint(monkeypatch, tmp_path):
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    calls = []

    def fake_main(argv):
        calls.append(argv)
        for path in argv:
            print(f"{path}: utf-8 with confidence 1.0")

    package = ModuleType("chardet")
    cli = ModuleType("chardet.cli")
    cli.main = fake_main
    package.cli = cli
    monkeypatch.setitem(sys.modules, "chardet", package)
    monkeypatch.setitem(sys.modules, "chardet.cli", cli)

    workload = adapter._chardet_workload(Path(tmp_path), limit=2)
    result = workload()

    assert calls == [[str(first), str(second)]]
    assert result == [
        f"{first}: utf-8 with confidence 1.0",
        f"{second}: utf-8 with confidence 1.0",
    ]
