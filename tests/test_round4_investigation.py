import copy
import csv
import json
import sys
from pathlib import Path

import pytest

import site_ip_investigator as inv


@pytest.fixture
def mock_site(monkeypatch, sample_data):
    def setup(*, resolves=True, registered=False, ok=False, error="NameResolutionError: failed to resolve", status=None):
        page = {
            "ok": ok, "status_code": status or (200 if ok else None),
            "final_url": "https://example.com/final" if ok else None,
            "headers": {}, "html": "", "error": None if ok else error,
        }
        dns_data = copy.deepcopy(sample_data["dns"])
        if not resolves:
            dns_data.update({"a_records": [], "aaaa_records": [], "cname_records": [], "nameservers": []})
        rdap = {"raw_available": registered, "registrar": "Example Registrar" if registered else None}
        monkeypatch.setattr(inv, "fetch_page", lambda url: copy.deepcopy(page))
        monkeypatch.setattr(inv, "dns_lookup", lambda host: copy.deepcopy(dns_data))
        monkeypatch.setattr(inv, "rdap_lookup", lambda domain: copy.deepcopy(rdap))
        monkeypatch.setattr(inv, "ip_asn_lookup", lambda ip: {"ip": ip})
        return page, dns_data, rdap
    return setup


@pytest.mark.parametrize("suffix,platform", inv.SHARED_PLATFORM_SUFFIXES.items())
def test_platform_subdomains_skip_registrar_and_use_host(monkeypatch, tmp_path, sample_data, suffix, platform):
    hostname = f"your-copycat-store.{suffix}"
    url = f"https://{hostname}/products/test?variant=1"
    calls = []
    def dns(host):
        calls.append(("dns", host))
        return copy.deepcopy(sample_data["dns"])
    def fetch(target):
        calls.append(("http", target))
        return {"ok": True, "status_code": 200, "final_url": target,
                "headers": {"cf-ray": "test", "X-CDN": "shopifycdn"}, "html": "", "error": None}
    def forbidden(*args):
        pytest.fail("A platform-owned subdomain must not query registrar RDAP or IP ASN")
    monkeypatch.setattr(inv, "dns_lookup", dns)
    monkeypatch.setattr(inv, "fetch_page", fetch)
    monkeypatch.setattr(inv, "rdap_lookup", forbidden)
    monkeypatch.setattr(inv, "ip_asn_lookup", forbidden)
    data = inv.investigate(url, inv.BrandInfo(), tmp_path)
    assert calls == [("http", url), ("dns", hostname)]
    assert data["hostname"] == hostname
    assert data["registrable_domain"] == suffix
    assert data["shared_platform_subdomain"] is True
    assert data["rdap"]["status"] == f"skipped: domain belongs to {platform}"
    assert data["detected"]["hosting"]["status"] == "platform_hosted"
    assert data["detected"]["hosting"]["provider"] == platform
    assert [item["target"] for item in data["complaint_priority"]] == [platform, "Google Search Removal"]
    report = inv.deterministic_report(data)
    assert f"This store is on {platform}'s own domain; report it to {platform}, not the domain registrar." in report
    assert f"Infringing Page URL: {url}" in report
    if platform == "Shopify":
        assert "Shopify CDN" not in [item["name"] for item in data["detected"]["cdn"]]


@pytest.mark.parametrize("host", ["myshopify.com", "notmyshopify.com", "store.myshopify.com.evil.example"])
def test_platform_suffix_requires_subdomain_boundary(host):
    assert inv.shared_platform_for_host(host) is None


@pytest.mark.parametrize("value", ["not a url", "localhost", "https://", "bad_host.example", "-bad.example", "bad-.example", "bad..example", "ftp://example.com", "https://example.com:70000", "https://exam\nple.com", "https://[broken]/"])
def test_invalid_input_exits_two_without_outputs(monkeypatch, tmp_path, capsys, value):
    monkeypatch.setattr(sys, "argv", ["investigator", f"--url={value}", "--output-dir", str(tmp_path)])
    assert inv.main() == 2
    assert "is not a valid URL or domain" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("value,expected", [
    (" Store.Example.com/products/a?x=1 ", "https://store.example.com/products/a?x=1"),
    ("https://Store.Example.com.:8443/a", "https://store.example.com:8443/a"),
    ("192.0.2.10", "https://192.0.2.10"),
    ("2001:db8::10", "https://[2001:db8::10]"),
])
def test_normalization_preserves_full_host_and_page(value, expected):
    assert inv.normalize_url(value) == expected


def test_nonexistent_domain_exits_three_and_only_writes_json(mock_site, monkeypatch, tmp_path, capsys):
    mock_site(resolves=False)
    def forbidden(*args, **kwargs):
        pytest.fail("Missing domains must not produce screenshots or complaint reports")
    monkeypatch.setattr(inv, "deterministic_report", forbidden)
    monkeypatch.setattr(inv, "llm_report", forbidden)
    monkeypatch.setattr(inv, "screenshot_page", forbidden)
    monkeypatch.setattr(inv, "write_pdf", forbidden)
    monkeypatch.setattr(sys, "argv", ["investigator", "--url", "thisdomaindoesnotexist-zz9.com", "--output-dir", str(tmp_path), "--screenshots", "--pdf", "--llm", "openai"])
    assert inv.main() == 3
    assert "Could not confirm thisdomaindoesnotexist-zz9.com from DNS, RDAP or HTTP. Check the URL for typos and retry; network or lookup service failures can also cause this result." in capsys.readouterr().err
    record, = tmp_path.rglob("investigation.json")
    data = json.loads(record.read_text())
    assert data["domain_not_found"] is True
    assert data["complaint_priority"] == []
    assert "NameResolutionError" in data["http"]["error"]
    assert not list(tmp_path.rglob("report.*"))


@pytest.mark.parametrize("resolves,registered,ok", [(True, False, False), (False, True, False), (False, False, True)])
def test_existing_domains_keep_reports(mock_site, tmp_path, resolves, registered, ok):
    mock_site(resolves=resolves, registered=registered, ok=ok, error="ReadTimeout: internals timed out")
    args = inv.build_parser().parse_args(["--url", "example.com", "--output-dir", str(tmp_path)])
    assert inv.single_mode(args) == 0
    report, = tmp_path.rglob("report.md")
    text = report.read_text()
    if not ok:
        assert "The page could not be loaded (timed out after 20s). Capture your own screenshot as evidence before filing." in text.split("## 1.")[0]
        assert "ReadTimeout" not in text


@pytest.mark.parametrize("record", ["aaaa_records", "cname_records"])
def test_ipv6_or_cname_only_is_not_missing(mock_site, monkeypatch, tmp_path, record):
    _, dns_data, _ = mock_site(resolves=False)
    dns_data[record] = ["2001:db8::10" if record == "aaaa_records" else "target.example.com"]
    monkeypatch.setattr(inv, "dns_lookup", lambda host: dns_data)
    assert inv.investigate("example.com", inv.BrandInfo(), tmp_path)["domain_not_found"] is False


@pytest.mark.parametrize("error,expected", [
    (inv.requests.ConnectionError("HTTPSConnectionPool(host='missing.example'): NameResolutionError: Failed to resolve"), "domain not found"),
    (inv.dns.resolver.NXDOMAIN(), "domain not found"),
    (inv.requests.Timeout(), "timed out after 20s"),
    (inv.requests.exceptions.SSLError("sensitive transport details"), "SSL certificate error"),
    (inv.requests.ConnectionError("[Errno 61] Connection refused"), "connection refused"),
    ("HTTP 404", "HTTP 404"),
])
def test_readable_transport_errors(error, expected):
    assert inv.readable_error(error) == expected


def test_empty_timeout_exception_keeps_readable_report_reason(mock_site, monkeypatch, tmp_path):
    original_fetch = inv.fetch_page
    mock_site()
    def timeout(*args, **kwargs):
        raise inv.requests.Timeout()
    monkeypatch.setattr(inv.requests, "get", timeout)
    monkeypatch.setattr(inv, "fetch_page", original_fetch)
    data = inv.investigate("example.com", inv.BrandInfo(), tmp_path)
    assert inv.summarize_for_console(data)["error"] == "timed out after 20s"
    assert "The page could not be loaded (timed out after 20s)" in inv.deterministic_report(data)


def test_batch_invalid_and_missing_rows_continue_with_readable_errors(mock_site, tmp_path):
    mock_site(resolves=False)
    source = tmp_path / "sites.csv"
    source.write_text("url\nnot a url\nmissing.example\n", encoding="utf-8")
    args = inv.build_parser().parse_args(["--csv", str(source), "--output-dir", str(tmp_path / "out")])
    assert inv.batch_mode(args) == 0
    summary_path, = (tmp_path / "out").rglob("batch_summary.csv")
    with summary_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["error"] == "'not a url' is not a valid URL or domain"
    assert rows[1]["error"] == "domain not found"
    assert all(row["report_md"] == "" for row in rows)
    assert all((Path(row["output_dir"]) / "investigation.json").is_file() for row in rows)
    assert "NameResolutionError" not in summary_path.with_suffix(".md").read_text()
    assert not list((tmp_path / "out").rglob("report.md"))


def test_shopify_cdn_removed_for_detected_platform(run_investigation):
    data = run_investigation(html="Shopify.theme", headers={"X-CDN": "shopifycdn"})
    assert "Shopify" in [item["name"] for item in data["detected"]["platforms"]]
    assert "Shopify CDN" not in [item["name"] for item in data["detected"]["cdn"]]
