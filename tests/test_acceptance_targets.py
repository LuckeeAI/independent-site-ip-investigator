"""Acceptance coverage for incomplete DNS/RDAP evidence and HTTP failures."""

import copy
import json

import pytest

import site_ip_investigator as inv


@pytest.mark.parametrize("status", [403, 404, 503])
@pytest.mark.parametrize("lang", ["en", "zh"])
def test_http_response_keeps_report_when_dns_and_rdap_are_unavailable(
    monkeypatch, tmp_path, sample_data, status, lang,
):
    dns = copy.deepcopy(sample_data["dns"])
    dns.update(nameservers=[], a_records=[], aaaa_records=[], cname_records=[])
    dns["errors"] = {"A": "DNS service timed out"}
    monkeypatch.setattr(inv, "dns_lookup", lambda host: dns)
    monkeypatch.setattr(inv, "safe_request_json", lambda url: None)

    class Response:
        status_code = status
        url = "https://shop.example.com/products/original?variant=1"
        headers = {}
        text = "<html>Page unavailable</html>"

    monkeypatch.setattr(inv.requests, "get", lambda *args, **kwargs: Response())
    args = inv.build_parser().parse_args([
        "--url", Response.url, "--lang", lang, "--output-dir", str(tmp_path),
    ])

    assert inv.single_mode(args) == 0
    record, = tmp_path.rglob("investigation.json")
    data = json.loads(record.read_text(encoding="utf-8"))
    assert data["domain_not_found"] is False
    assert data["http"]["ok"] is False
    assert data["http"]["status_code"] == status
    report, = tmp_path.rglob("report.md")
    text = report.read_text(encoding="utf-8")
    assert f"HTTP {status}" in text.split("## 1.")[0]
    assert "请自行截图留存证据" in text if lang == "zh" else "Capture your own screenshot" in text
    assert f"Infringing Page URL: {Response.url}" in text


def test_lookup_outage_does_not_claim_domain_is_unregistered(monkeypatch, tmp_path, capsys):
    def timeout(*args, **kwargs):
        raise inv.requests.Timeout("simulated lookup outage")

    monkeypatch.setattr(inv.requests, "get", timeout)
    monkeypatch.setattr(inv.dns.resolver, "resolve", timeout)
    # Exercise the RDAP parser's no-response path without making network calls.
    monkeypatch.setattr(inv, "safe_request_json", lambda url: None)
    args = inv.build_parser().parse_args([
        "--url", "store.example.com", "--output-dir", str(tmp_path),
    ])

    assert inv.single_mode(args) == 3
    message = capsys.readouterr().err
    assert "Could not confirm store.example.com" in message
    assert "network or lookup service failures" in message
    assert "not registered" not in message
    assert "does not exist" not in message
    record, = tmp_path.rglob("investigation.json")
    data = json.loads(record.read_text(encoding="utf-8"))
    assert data["domain_not_found"] is True
    assert data["error"] == "domain not found"
    assert data["http"]["error_summary"] == "timed out after 20s"
    assert data["complaint_priority"] == []
    assert not list(tmp_path.rglob("report.*"))
