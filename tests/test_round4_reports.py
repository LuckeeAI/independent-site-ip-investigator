import copy
import sys
import types

import pytest

import site_ip_investigator as inv


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_redirect_appears_only_in_basic_info_and_templates_keep_input(sample_data, lang):
    sample_data.update(hostname="shop.example.com", registrable_domain="example.com")
    sample_data["input_url"] = "https://shop.example.com/products/original?variant=1"
    report = inv.deterministic_report(sample_data, lang=lang)
    basic, templates = report.split("## 2.", 1)[0], report.split("## 8.", 1)[1]
    assert "shop.example.com" in basic
    assert "example.com" in basic
    assert sample_data["http"]["final_url"] in basic
    assert report.count(sample_data["http"]["final_url"]) == 1
    assert templates.count(f"Infringing Page URL: {sample_data['input_url']}") == 3
    assert "Infringing Website / Domain: shop.example.com" in templates


def test_identical_url_has_no_redirect_line(sample_data):
    sample_data["http"]["final_url"] = sample_data["input_url"]
    report = inv.deterministic_report(sample_data)
    assert "Redirects to:" not in report
    assert "HTTP error: No error recorded." in report
    assert "Warning:" not in report


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_shared_platform_report_excludes_registrar_and_cdn_priorities(sample_data, lang):
    sample_data.update(
        hostname="copycat.myshopify.com", registrable_domain="myshopify.com",
        input_url="https://copycat.myshopify.com/product", shared_platform_subdomain=True,
        shared_platform="Shopify",
    )
    sample_data["rdap"] = {"status": "skipped: domain belongs to Shopify"}
    sample_data["detected"]["hosting"] = {"status": "platform_hosted", "provider": "Shopify"}
    # A shared platform cannot inherit inappropriate recommendations from stale data.
    sample_data["complaint_priority"] = [{"target": "MarkMonitor", "reason": "Registrar"}, {"target": "Cloudflare", "reason": "CDN"}]
    priorities = inv.build_priority([], [{"name": "Cloudflare"}], {"status": "visible"}, {"registrar": "MarkMonitor"}, shared_platform="Shopify", registrable_domain="myshopify.com")
    assert [item["target"] for item in priorities] == ["Shopify", "Google Search Removal"]
    report = inv.deterministic_report(sample_data, lang=lang)
    section = report.split("## 6.", 1)[1].split("## 7.", 1)[0]
    assert "1. **Shopify**" in section
    assert "2. **Google Search Removal**" in section
    assert "MarkMonitor" not in section
    assert "Cloudflare" not in section
    if lang == "en":
        assert "This store is on Shopify's own domain; report it to Shopify, not the domain registrar." in report
        assert "Registrar complaint URL: Not applicable: registrar RDAP was skipped." in report
    else:
        assert "不要向域名注册商投诉" in report


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_registrar_priority_shows_abuse_contacts_and_known_url(sample_data, lang):
    sample_data["rdap"].update(
        registrar="NameCheap, Inc.", abuse_email="abuse@example.net", abuse_phone="+1.5555550100",
    )
    sample_data["complaint_priority"] = inv.build_priority([], [], {}, sample_data["rdap"], registrable_domain="example.com")
    report = inv.deterministic_report(sample_data, lang=lang)
    section = report.split("## 6.", 1)[1].split("## 7.", 1)[0]
    assert "Email abuse@example.net" in section
    assert "Phone +1.5555550100" in section
    assert inv.REGISTRAR_COMPLAINT_URLS["namecheap"] in section
    assert "Channel: " in section if lang == "en" else "（入口：" in section
    assert all(bad not in report for bad in ("。；", "；；", ".;"))


def test_registrar_without_email_or_complaint_url_uses_icann(sample_data):
    sample_data["rdap"]["abuse_phone"] = "+1.5555550100"
    priority = inv.build_priority([], [], {}, sample_data["rdap"], registrable_domain="example.com")
    registrar = next(item for item in priority if item.get("kind") == "registrar")
    assert registrar["url"] == "https://lookup.icann.org/en/lookup?name=example.com"
    assert "Phone +1.5555550100" in registrar["channel"]
    assert "rdap.org" not in registrar["channel"]


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("error,status,expected", [
    ("HTTPSConnectionPool(host='example.com', port=443): Read timed out. (read timeout=20)", None, "timed out after 20s"),
    ("SSLError: certificate verify failed in urllib3", None, "SSL certificate error"),
    ("Connection refused: raw low-level traceback", None, "connection refused"),
    (None, 403, "HTTP 403"),
])
def test_unloaded_page_has_prominent_readable_warning(sample_data, lang, error, status, expected):
    sample_data["http"].update(ok=False, error=error, status_code=status)
    original = copy.deepcopy(sample_data)
    report = inv.deterministic_report(sample_data, lang=lang)
    top = report.split("## 1.", 1)[0]
    assert expected in top
    assert "Capture your own screenshot as evidence before filing." in top if lang == "en" else "请自行截图留存证据" in top
    if error:
        assert error not in report
    assert sample_data == original


def test_llm_receives_input_url_rule_and_sanitized_errors(monkeypatch, sample_data):
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    sample_data["http"].update(ok=False, error="Connection refused: raw socket details", status_code=None)
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return types.SimpleNamespace(output_text="# Report")
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=lambda **kwargs: types.SimpleNamespace(responses=types.SimpleNamespace(create=create))))
    assert inv.llm_report(sample_data, provider="openai") == "# Report"
    prompt = calls[0]["input"]
    assert "Use input_url as the Infringing Page URL in every template" in prompt
    assert "Do not recommend the registrar or CDN for shared platform subdomains" in prompt
    assert "raw socket details" not in prompt
    assert '"error": "connection refused"' in prompt


def test_empty_typed_exception_retains_readable_summary(sample_data):
    sample_data["http"].update(ok=False, error="", error_summary="timed out after 20s", status_code=None)
    report = inv.deterministic_report(sample_data)
    assert "The page could not be loaded (timed out after 20s)." in report
    assert inv._report_safe_evidence(sample_data)["http"]["error"] == "timed out after 20s"


def test_raw_errors_are_omitted_when_saved_evidence_is_reused():
    evidence = {"pdf": {"error": "request failed", "raw_error": "private library path"}}
    assert "raw_error" not in inv._report_safe_evidence(evidence)["pdf"]
