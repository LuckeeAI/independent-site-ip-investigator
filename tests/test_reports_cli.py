import builtins
import copy
import csv
import re
import sys
import types
from contextlib import contextmanager
from pathlib import Path

import pytest

import site_ip_investigator as inv


EN_HEADINGS = [
    "Basic Information", "Domain Registrar / RDAP", "DNS / Name Servers",
    "Service Provider Detection", "Screenshot Evidence", "Recommended Complaint Priority",
    "Evidence Checklist", "English Copyright / DMCA Complaint Template",
    "English Trademark Complaint Template", "Amazon Buy Box / Featured Offer Case Template",
    "Important Notes",
]
ZH_HEADINGS = [
    "基础信息", "域名注册商 / RDAP", "DNS / Name Server", "服务商识别结果", "截图证据",
    "建议投诉优先级", "建议准备的证据材料", "英文 Copyright / DMCA 投诉模板",
    "英文 Trademark 投诉模板", "Amazon Buy Box / Featured Offer Case 模板", "注意事项",
]


@pytest.mark.parametrize("template", [inv.dmca_template, inv.trademark_template, inv.amazon_case_template])
def test_templates_include_complete_real_page_url(template, sample_data):
    url = "https://example.com/products/sample?variant=red&size=2"
    result = template(sample_data["brand_info"], "example.com", url)
    assert f"Infringing Page URL: {url}" in result
    assert "[Insert infringing page URL]" not in result


@pytest.mark.parametrize("lang,headings", [("en", EN_HEADINGS), ("zh", ZH_HEADINGS)])
def test_cli_language_renders_all_eleven_sections(lang, headings, sample_data, tmp_path):
    args = inv.build_parser().parse_args(["--url", sample_data["input_url"], "--lang", lang])
    paths = inv.save_single_report(sample_data, tmp_path, llm=args.llm, lang=args.lang)
    report = Path(paths["markdown"]).read_text(encoding="utf-8")
    assert re.findall(r"^## (.+)$", report, re.MULTILINE) == [f"{number}. {title}" for number, title in enumerate(headings, 1)]
    assert report.count(f"Infringing Page URL: {sample_data['input_url']}") == 3
    assert "Dear Legal / Abuse Team" in report
    assert "Dear Amazon Seller Support Team" in report


def test_report_defaults_to_english_and_falls_back_to_input_url(sample_data):
    sample_data["http"]["final_url"] = None
    report = inv.deterministic_report(sample_data)
    assert "## 1. Basic Information" in report
    assert report.count(f"Infringing Page URL: {sample_data['input_url']}") == 3


def test_cli_defaults_and_hidden_legacy_flag():
    parser = inv.build_parser()
    args = parser.parse_args(["--url", "example.com"])
    assert args.lang == "en"
    assert args.llm == "none"
    assert parser.parse_args(["--url", "example.com", "--llm", "anthropic"]).llm == "anthropic"
    assert parser.parse_args(["--url", "example.com", "--llm", "openai", "--no-llm"]).llm == "none"
    assert "--no-llm" not in parser.format_help()
    assert "--lang" in parser.format_help()
    assert "--llm" in parser.format_help()


def test_cli_version_does_not_require_target(capsys):
    with pytest.raises(SystemExit) as exc:
        inv.build_parser().parse_args(["--version"])
    assert exc.value.code == 0
    assert "1.2.0" in capsys.readouterr().out


@pytest.mark.parametrize("lang,title", [("en", "Batch Investigation Summary"), ("zh", "批量调查汇总")])
def test_batch_continues_after_failing_first_row(monkeypatch, tmp_path, sample_data, lang, title):
    source = tmp_path / "sites.csv"
    source.write_text("url,brand\nhttps://broken.example.com,Example\nhttps://example.com/product,Example\n", encoding="utf-8")
    seen = []
    def investigate(url, brand, out_dir, do_screenshots=False):
        seen.append(url)
        if "broken" in url:
            raise RuntimeError("simulated lookup failure")
        return copy.deepcopy(sample_data)
    monkeypatch.setattr(inv, "investigate", investigate)
    args = inv.build_parser().parse_args(["--csv", str(source), "--output-dir", str(tmp_path / "reports"), "--lang", lang])
    assert inv.batch_mode(args) == 0
    assert seen == ["https://broken.example.com", "https://example.com/product"]
    summary_path, = (tmp_path / "reports").rglob("batch_summary.csv")
    with summary_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert rows[0]["url"] == seen[0]
    assert rows[0]["error"] == "request failed"
    record = Path(rows[0]["output_dir"]) / "investigation.json"
    assert "simulated lookup failure" in record.read_text(encoding="utf-8")
    assert rows[1]["url"] == seen[1]
    assert rows[1]["error"] == ""
    assert Path(rows[1]["report_md"]).is_file()
    summary = summary_path.with_suffix(".md").read_text(encoding="utf-8")
    assert title in summary
    assert "request failed" in summary
    assert "simulated lookup failure" not in summary


def test_llm_is_opt_in_even_when_credentials_exist(monkeypatch, sample_data):
    for prefix in ("OPENAI", "ANTHROPIC"):
        monkeypatch.setenv(f"{prefix}_API_KEY", "dummy-test-key")
        monkeypatch.setenv(f"{prefix}_MODEL", "test-model")
    real_import = builtins.__import__
    def import_guard(name, *args, **kwargs):
        if name in {"openai", "anthropic"}:
            pytest.fail("Default report generation must not import optional LLM SDKs")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", import_guard)
    assert inv.llm_report(sample_data) is None


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.parametrize("missing", ["API_KEY", "MODEL"])
def test_missing_llm_configuration_warns_clearly(monkeypatch, capsys, sample_data, provider, missing):
    prefix = provider.upper()
    other = "MODEL" if missing == "API_KEY" else "API_KEY"
    monkeypatch.setenv(f"{prefix}_{other}", "dummy-test-value")
    assert inv.llm_report(sample_data, provider=provider) is None
    captured = capsys.readouterr()
    assert f"{prefix}_{missing}" in captured.err
    assert captured.out == ""


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.parametrize("lang,language", [("en", "English"), ("zh", "Chinese")])
def test_optional_provider_apis_receive_explicit_model_and_language(monkeypatch, sample_data, provider, lang, language):
    calls = []
    keys = []
    monkeypatch.setenv(f"{provider.upper()}_API_KEY", "dummy-test-key")
    monkeypatch.setenv(f"{provider.upper()}_MODEL", "explicit-test-model")
    def create(**kwargs):
        calls.append(kwargs)
        if provider == "openai":
            return types.SimpleNamespace(output_text="# Provider report")
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="# Provider report"), types.SimpleNamespace(type="tool_use")])
    def client(**kwargs):
        keys.append(kwargs)
        endpoint = types.SimpleNamespace(create=create)
        return types.SimpleNamespace(responses=endpoint, messages=endpoint)
    monkeypatch.setitem(sys.modules, provider, types.SimpleNamespace(**{"OpenAI" if provider == "openai" else "Anthropic": client}))
    assert inv.llm_report(sample_data, provider=provider, lang=lang) == "# Provider report"
    assert keys == [{"api_key": "dummy-test-key"}]
    assert calls[0]["model"] == "explicit-test-model"
    prompt = calls[0]["input"] if provider == "openai" else calls[0]["messages"][0]["content"]
    assert f"in {language}" in prompt
    assert sample_data["http"]["final_url"] in prompt
    assert "templates in English" in prompt


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_provider_failure_warns_to_stderr_and_saves_clean_fallback(monkeypatch, capsys, tmp_path, sample_data, provider):
    monkeypatch.setenv(f"{provider.upper()}_API_KEY", "dummy-test-key")
    monkeypatch.setenv(f"{provider.upper()}_MODEL", "explicit-test-model")
    def fail(**kwargs):
        raise RuntimeError("simulated provider failure")
    monkeypatch.setitem(sys.modules, provider, types.SimpleNamespace(**{"OpenAI" if provider == "openai" else "Anthropic": fail}))
    paths = inv.save_single_report(sample_data, tmp_path, llm=provider, lang="zh")
    report = Path(paths["markdown"]).read_text(encoding="utf-8")
    assert report == inv.deterministic_report(sample_data, lang="zh")
    assert "simulated provider failure" not in report
    assert "simulated provider failure" in capsys.readouterr().err


def test_screenshot_retries_load_after_networkidle_timeout(monkeypatch, tmp_path):
    calls = []
    closed = []
    class BrowserTimeout(Exception):
        pass
    class Page:
        def goto(self, url, **kwargs):
            calls.append((url, kwargs["wait_until"]))
            if kwargs["wait_until"] == "networkidle":
                raise BrowserTimeout("network remains active")
        def screenshot(self, **kwargs):
            Path(kwargs["path"]).write_bytes(b"test screenshot")
    browser = types.SimpleNamespace(new_page=lambda **kwargs: Page(), close=lambda: closed.append(True))
    playwright = types.SimpleNamespace(chromium=types.SimpleNamespace(launch=lambda **kwargs: browser))
    @contextmanager
    def sync_playwright():
        yield playwright
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", types.SimpleNamespace(sync_playwright=sync_playwright, TimeoutError=BrowserTimeout))
    result = inv.screenshot_page("https://example.com/product", tmp_path)
    assert calls == [("https://example.com/product", "networkidle"), ("https://example.com/product", "load")]
    assert result["error"] is None
    assert len(result["files"]) == 1
    assert Path(result["files"][0]).is_file()
    assert closed == [True]
