from pathlib import Path
import gzip
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
        "a.txt: utf-8 with confidence 1.0",
        "b.txt: utf-8 with confidence 1.0",
    ]


def test_relative_path_removes_machine_specific_prefix(tmp_path):
    nested = tmp_path / "package" / "module.py"
    nested.parent.mkdir()
    nested.touch()

    assert adapter._relative_path(nested, tmp_path) == "package/module.py"


def test_built_site_records_hashes_decompressed_gzip_content(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("hello", encoding="utf-8")
    with gzip.GzipFile(site / "sitemap.xml.gz", "wb", mtime=123) as stream:
        stream.write(b"<urlset />")

    records = adapter._built_site_records(site)

    assert [record["path"] for record in records] == [
        "index.html",
        "sitemap.xml.gz",
    ]
    assert records[1]["size"] == len(b"<urlset />")


def test_built_site_records_ignores_only_mkdocs_build_timestamp(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "index.html").write_text(
        "page\nBuild Date UTC : 2026-08-08 01:02:03+00:00\n",
        encoding="utf-8",
    )
    (second / "index.html").write_text(
        "page\nBuild Date UTC : 2026-08-08 09:08:07+00:00\n",
        encoding="utf-8",
    )

    assert adapter._built_site_records(first) == adapter._built_site_records(second)


def test_mkdocs_workload_uses_public_build_and_complete_site(monkeypatch, tmp_path):
    (tmp_path / "mkdocs.yml").write_text("site_name: Demo\n", encoding="utf-8")
    calls = []

    def fake_load_config(**kwargs):
        calls.append(("load", kwargs))
        return {"site_dir": kwargs["site_dir"]}

    def fake_build(config, dirty):
        calls.append(("build", dirty))
        site_dir = Path(config["site_dir"])
        site_dir.mkdir(parents=True)
        (site_dir / "index.html").write_text("rendered", encoding="utf-8")

    package = ModuleType("mkdocs")
    commands = ModuleType("mkdocs.commands")
    build_module = ModuleType("mkdocs.commands.build")
    config_module = ModuleType("mkdocs.config")
    build_module.build = fake_build
    config_module.load_config = fake_load_config
    package.commands = commands
    monkeypatch.setitem(sys.modules, "mkdocs", package)
    monkeypatch.setitem(sys.modules, "mkdocs.commands", commands)
    monkeypatch.setitem(sys.modules, "mkdocs.commands.build", build_module)
    monkeypatch.setitem(sys.modules, "mkdocs.config", config_module)

    workload = adapter._mkdocs_workload(tmp_path, limit=None)
    result = workload()

    assert calls[0][0] == "load"
    assert calls[1] == ("build", False)
    assert result[0]["path"] == "index.html"


def test_mkdocs_workload_rejects_partial_site_limit(tmp_path):
    try:
        adapter._mkdocs_workload(tmp_path, limit=10)
    except ValueError as exc:
        assert "complete registered site" in str(exc)
    else:
        raise AssertionError("expected the partial-site limit to be rejected")
