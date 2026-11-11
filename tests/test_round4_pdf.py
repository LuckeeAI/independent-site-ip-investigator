"""PDF dependency failures must leave readers with a usable Markdown report."""

import builtins
import json
import sys
import types

import pytest

import site_ip_investigator as inv


PDF_LIBRARY_MESSAGE = (
    "PDF needs system libraries for WeasyPrint. macOS: brew install pango; "
    "Ubuntu/Debian: apt install libpango-1.0-0 libpangoft2-1.0-0. "
    "The Markdown report was still written."
)


def test_pdf_import_oserror_is_readable_and_warns(monkeypatch, tmp_path, capsys):
    monkeypatch.setitem(sys.modules, "markdown2", types.SimpleNamespace())
    real_import = builtins.__import__

    def import_with_missing_library(name, *args, **kwargs):
        if name == "weasyprint":
            raise OSError("dlopen(/some/system/path/libpango.so): image not found")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_with_missing_library)
    details = {}
    assert inv.write_pdf("# Report", tmp_path / "report.pdf", details) == (False, PDF_LIBRARY_MESSAGE)
    assert details["error"] == PDF_LIBRARY_MESSAGE
    assert "dlopen(" in details["raw_error"]
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"WARNING: {PDF_LIBRARY_MESSAGE}\n"


@pytest.mark.parametrize("error", [OSError("missing native dependency"), RuntimeError("cannot load library 'pango'")])
def test_pdf_render_library_error_is_readable(monkeypatch, tmp_path, capsys, error):
    class HTML:
        def __init__(self, **kwargs):
            pass

        def write_pdf(self, path):
            raise error

    monkeypatch.setitem(sys.modules, "markdown2", types.SimpleNamespace(markdown=lambda *args, **kwargs: "<h1>Report</h1>"))
    monkeypatch.setitem(sys.modules, "weasyprint", types.SimpleNamespace(HTML=HTML))
    assert inv.write_pdf("# Report", tmp_path / "report.pdf") == (False, PDF_LIBRARY_MESSAGE)
    assert PDF_LIBRARY_MESSAGE in capsys.readouterr().err


def test_saved_pdf_dependency_failure_keeps_markdown_and_raw_json(monkeypatch, tmp_path, capsys, sample_data):
    raw_error = "dlopen(/private/system/libpango.dylib): missing system dependency"
    real_import = builtins.__import__

    def import_with_missing_library(name, *args, **kwargs):
        if name == "weasyprint":
            raise OSError(raw_error)
        return real_import(name, *args, **kwargs)

    monkeypatch.setitem(sys.modules, "markdown2", types.SimpleNamespace())
    monkeypatch.setattr(builtins, "__import__", import_with_missing_library)
    paths = inv.save_single_report(sample_data, tmp_path, make_pdf=True)
    assert paths["pdf_error"] == PDF_LIBRARY_MESSAGE
    assert "pdf" not in paths
    assert (tmp_path / "report.md").is_file()
    assert "# " in (tmp_path / "report.md").read_text(encoding="utf-8")
    saved = json.loads((tmp_path / "investigation.json").read_text(encoding="utf-8"))
    assert saved["pdf"] == {"error": PDF_LIBRARY_MESSAGE, "raw_error": raw_error}
    assert raw_error not in (tmp_path / "report.md").read_text(encoding="utf-8")
    assert raw_error not in json.dumps(paths)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"WARNING: {PDF_LIBRARY_MESSAGE}\n"
