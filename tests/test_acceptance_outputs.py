"""Regression coverage for optional PDF failures and batch reporting."""

import builtins
import copy
import csv
import errno
import json
import sys
import types
from pathlib import Path

import pytest

import site_ip_investigator as inv


def test_native_pdf_import_diagnostics_do_not_corrupt_cli_json(
    monkeypatch, tmp_path, capsys, sample_data,
):
    real_import = builtins.__import__

    def missing_library(name, *args, **kwargs):
        if name == "weasyprint":
            print("Third-party native library installation banner")
            raise OSError("cannot load library: private library path")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_library)
    monkeypatch.setattr(inv, "investigate", lambda *a, **kw: copy.deepcopy(sample_data))
    args = inv.build_parser().parse_args([
        "--url", sample_data["input_url"], "--pdf", "--output-dir", str(tmp_path),
    ])
    assert inv.single_mode(args) == 0
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert "PDF needs system libraries" in output["paths"]["pdf_error"]
    assert Path(output["paths"]["markdown"]).is_file()
    assert "private library path" not in captured.out + captured.err
    assert "installation banner" not in captured.out + captured.err


@pytest.mark.parametrize("module", ["markdown2", "weasyprint"])
def test_missing_pdf_python_package_warns_and_keeps_markdown(
    monkeypatch, tmp_path, capsys, sample_data, module,
):
    real_import = builtins.__import__

    def missing_package(name, *args, **kwargs):
        if name == module:
            raise ModuleNotFoundError(f"No module named '{module}'", name=module)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_package)
    paths = inv.save_single_report(sample_data, tmp_path, make_pdf=True)
    assert Path(paths["markdown"]).is_file()
    assert "pdf" not in paths
    assert "python -m pip install markdown2 weasyprint" in paths["pdf_error"]
    assert f"WARNING: {paths['pdf_error']}" in capsys.readouterr().err
    saved = json.loads(Path(paths["json"]).read_text())
    assert saved["pdf"]["raw_error"] == f"No module named '{module}'"


@pytest.mark.parametrize("error,expected", [
    (PermissionError("private path is read-only"), "permission denied"),
    (OSError(errno.ENOSPC, "private disk path is full"), "not enough disk space"),
    (RuntimeError("private renderer internals"), "PDF generation failed"),
])
def test_pdf_render_failures_are_not_reported_as_missing_system_libraries(
    monkeypatch, tmp_path, capsys, error, expected,
):
    class HTML:
        def __init__(self, **kwargs):
            pass

        def write_pdf(self, path):
            raise error

    monkeypatch.setitem(sys.modules, "markdown2", types.SimpleNamespace(markdown=lambda *a, **kw: "<p>Report</p>"))
    monkeypatch.setitem(sys.modules, "weasyprint", types.SimpleNamespace(HTML=HTML))
    details = {}
    ok, message = inv.write_pdf("# Report", tmp_path / "report.pdf", details)
    assert not ok
    assert expected in message
    assert "install pango" not in message
    assert "private" not in message
    assert details["raw_error"] == str(error)
    assert capsys.readouterr().err == f"WARNING: {message}\n"


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_batch_pdf_failure_is_counted_preserves_http_error_and_continues(
    monkeypatch, tmp_path, capsys, sample_data, lang,
):
    class HTML:
        def __init__(self, **kwargs):
            pass

        def write_pdf(self, path):
            if Path(path).parent.name.startswith("001_"):
                raise OSError("cannot load library: private native library path")
            Path(path).write_bytes(b"mock PDF")

    def investigate(url, brand, out_dir, do_screenshots=False):
        data = copy.deepcopy(sample_data)
        data["input_url"] = url
        if "blocked" in url:
            data["http"].update(ok=False, status_code=403, error="HTTP 403")
        return data

    monkeypatch.setitem(sys.modules, "markdown2", types.SimpleNamespace(markdown=lambda *a, **kw: "<p>Report</p>"))
    monkeypatch.setitem(sys.modules, "weasyprint", types.SimpleNamespace(HTML=HTML))
    monkeypatch.setattr(inv, "investigate", investigate)
    targets = tmp_path / "sites.csv"
    targets.write_text("url\nhttps://blocked.example/a\nhttps://working.example/b\n")
    args = inv.build_parser().parse_args([
        "--csv", str(targets), "--pdf", "--lang", lang,
        "--output-dir", str(tmp_path / "reports"),
    ])
    assert inv.batch_mode(args) == 0
    summary_path, = (tmp_path / "reports").rglob("batch_summary.csv")
    with summary_path.open(newline="") as handle:
        failed, succeeded = list(csv.DictReader(handle))
    assert "HTTP 403" in failed["error"]
    assert "PDF needs system libraries" in failed["error"]
    assert "private" not in failed["error"]
    assert not failed["report_pdf"]
    assert Path(failed["report_md"]).is_file()
    assert succeeded["error"] == ""
    assert Path(succeeded["report_pdf"]).is_file()
    assert Path(succeeded["report_md"]).is_file()
    summary = summary_path.with_suffix(".md").read_text()
    assert ("Rows with errors: 1" if lang == "en" else "出错行数: 1") in summary
    output = capsys.readouterr()
    assert "WARNING: PDF needs system libraries" in output.err
    assert "private native library path" not in output.out + output.err
