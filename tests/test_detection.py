import datetime as dt
import types

import pytest

import site_ip_investigator as inv


def names(items):
    return {item["name"] for item in items}


def test_third_party_cdn_assets_and_ips_in_html_do_not_identify_host(run_investigation):
    data = run_investigation(html="""
        <script src="https://cdnjs.cloudflare.com/library.js"></script>
        <link href="https://fonts.gstatic.com/font.woff">
        <script src="https://googlesyndication.com/ad.js"></script>
        <img src="https://googleusercontent.com/image.png">
        <p>cloudflare cf-ray 104.16.1.1 173.245.48.1</p>
        <script src="https://js.stripe.com/v3"></script>
    """)
    assert names(data["detected"]["cdn"]) == set()
    assert data["detected"]["hosting"]["status"] == "visible"
    assert "Stripe" in names(data["detected"]["payments_possible"])


@pytest.mark.parametrize("headers", [{"CF-RAY": "abc123"}, {"SERVER": "CloudFlare"}])
def test_cloudflare_headers_are_case_insensitive(run_investigation, headers):
    data = run_investigation(headers=headers)
    assert "Cloudflare" in names(data["detected"]["cdn"])
    assert data["detected"]["hosting"]["status"] == "hidden_by_cloudflare"


@pytest.mark.parametrize("address", ["173.245.48.1", "104.16.0.1", "131.0.72.254"])
def test_cloudflare_ipv4_ranges_detect_without_headers(run_investigation, address):
    data = run_investigation(dns={"a_records": [address]})
    assert "Cloudflare" in names(data["detected"]["cdn"])


@pytest.mark.parametrize("address", ["173.245.47.255", "131.0.76.0", "192.0.2.5"])
def test_addresses_outside_cloudflare_ranges_do_not_detect(run_investigation, address):
    data = run_investigation(dns={"a_records": [address]})
    assert "Cloudflare" not in names(data["detected"]["cdn"])


@pytest.mark.parametrize("dns", [
    {"nameservers": ["alice.ns.cloudflare.com"]},
    {"cname_records": ["example.cdn.cloudflare.net"]},
])
def test_cloudflare_dns_evidence_detects(run_investigation, dns):
    assert "Cloudflare" in names(run_investigation(dns=dns)["detected"]["cdn"])


@pytest.mark.parametrize("headers,dns", [
    ({"SeRvEr": "GWS"}, {}),
    ({"Via": "1.1 Google"}, {}),
    ({}, {"cname_records": ["ghs.googlehosted.com"]}),
])
def test_google_cdn_requires_infrastructure_signals(run_investigation, headers, dns):
    data = run_investigation(headers=headers, dns=dns)
    assert "Google CDN" in names(data["detected"]["cdn"])


def test_header_name_value_boundary_is_preserved(run_investigation):
    data = run_investigation(headers={"server": "unrelated", "gws": "unrelated"})
    assert "Google CDN" not in names(data["detected"]["cdn"])


@pytest.mark.parametrize("platform,html,headers,dns", [
    ("Shopify", "cdn.shopify.com Shopify.theme", {}, {}),
    ("Shopify", "", {}, {"cname_records": ["shops.myshopify.com"]}),
    ("Shopify", "", {}, {"a_records": ["23.227.38.65"]}),
    ("Wix", "", {}, {"cname_records": ["www42.wixdns.net"]}),
    ("Wix", "", {"Server": "Pepyaka"}, {}),
    ("Squarespace", "", {}, {"a_records": ["198.185.159.144"]}),
    ("Squarespace", "", {}, {"a_records": ["198.49.23.144"]}),
    ("BigCommerce", "cdn11.bigcommerce.com mybigcommerce.com", {}, {}),
])
def test_hosted_platform_takes_precedence_over_cloudflare(run_investigation, platform, html, headers, dns):
    data = run_investigation(html=html, headers={"cf-ray": "example", **headers}, dns=dns)
    hosting = data["detected"]["hosting"]
    assert hosting["status"] == "platform_hosted"
    assert hosting["provider"] == platform
    assert hosting["complaint_url"] == inv.SERVICE_COMPLAINT_URLS[platform]
    assert "host" in hosting["note"].lower()
    assert "primary" in hosting["note"].lower()


def test_medium_platform_signal_does_not_override_hidden_origin(run_investigation):
    data = run_investigation(html="cdn.shopify.com", headers={"cf-ray": "example"})
    assert data["detected"]["hosting"]["status"] == "hidden_by_cloudflare"


@pytest.mark.parametrize("generic", ["stencil", "/cart.js", "static/version", "mage/", "wix.com", "myshopifyy"])
def test_generic_platform_keywords_do_not_detect(generic):
    assert inv.detect_by_rules(generic, inv.PLATFORM_RULES) == []


@pytest.mark.parametrize("text,platform,confidence", [
    ("shopyy", "Shopyy", "medium"),
    ("wixstatic.com", "Wix", "medium"),
    ("X-Wix", "Wix", "medium"),
    ("Shopify.theme Shopify.theme", "Shopify", "medium"),
    ("Shopify.theme shopifycloud", "Shopify", "high"),
])
def test_distinct_platform_matches_control_confidence(text, platform, confidence):
    result = inv.detect_by_rules(text, inv.PLATFORM_RULES)
    assert [(item["name"], item["confidence"]) for item in result] == [(platform, confidence)]


def test_header_platform_and_payment_signals_are_used(run_investigation):
    data = run_investigation(headers={"X-Wix": "yes", "Content-Security-Policy": "script-src https://js.stripe.com"})
    assert "Wix" in names(data["detected"]["platforms"])
    assert "Stripe" in names(data["detected"]["payments_possible"])


def test_priority_uses_first_credible_platform_then_cdn_host_registrar_search():
    priority = inv.build_priority(
        [{"name": "Shopify", "confidence": "low"}, {"name": "Wix", "confidence": "medium"}, {"name": "BigCommerce", "confidence": "high"}],
        [{"name": "Cloudflare", "confidence": "medium"}],
        {"status": "visible", "asn": {"asn_description": "Example Host"}},
        {"registrar": "Example Registrar", "complaint_url_guess": "https://example.net/abuse"},
    )
    assert [item["target"] for item in priority] == ["Wix", "Cloudflare", "Example Host", "Example Registrar", "Google Search Removal"]
    assert priority[0]["url"] == inv.SERVICE_COMPLAINT_URLS["Wix"]
    assert priority[3]["url"] == "https://example.net/abuse"


def test_medium_platform_without_known_complaint_url_still_gets_priority():
    priority = inv.build_priority([{"name": "Shopyy", "confidence": "medium"}], [], {"status": "unknown"}, {})
    assert priority[0]["target"] == "Shopyy"
    assert priority[0]["url"] == ""


@pytest.mark.parametrize("value,expected", [
    ("192.0.2.10", "192.0.2.10"),
    ("https://192.0.2.10:8443/product", "192.0.2.10"),
    ("2001:db8::10", "2001:db8::10"),
    ("https://[2001:db8::10]/product", "2001:db8::10"),
])
def test_extract_domain_preserves_ip(value, expected):
    assert inv.extract_domain(value) == expected


@pytest.mark.parametrize("address,key", [("192.0.2.10", "a_records"), ("2001:db8::10", "aaaa_records")])
def test_ip_input_skips_domain_rdap_and_dns_queries(address, key):
    rdap = inv.rdap_lookup(address)
    assert rdap["status"] == "skipped"
    assert "IP" in rdap["note"]
    assert inv.dns_lookup(address)[key] == [address]


def test_bare_ip_investigation_records_skip_and_aware_timestamp(monkeypatch, tmp_path):
    monkeypatch.setattr(inv, "fetch_page", lambda url: {"ok": True, "status_code": 200, "final_url": url, "headers": {}, "html": "", "error": None})
    monkeypatch.setattr(inv, "ip_asn_lookup", lambda ip: {"ip": ip})
    data = inv.investigate("192.0.2.10", inv.BrandInfo(), tmp_path)
    assert data["domain"] == "192.0.2.10"
    assert data["rdap"]["status"] == "skipped"
    assert "IP" in inv.deterministic_report(data)
    assert "输入为 IP 地址，已跳过域名 RDAP 查询。" in inv.deterministic_report(data, lang="zh")
    assert dt.datetime.fromisoformat(data["generated_at_utc"].replace("Z", "+00:00")).utcoffset() == dt.timedelta(0)


def test_subdomain_dns_is_preserved_while_rdap_uses_registered_domain(monkeypatch, tmp_path, sample_data):
    queries = []
    def dns_lookup(host):
        queries.append(("dns", host))
        return {**sample_data["dns"], "cname_records": ["shops.myshopify.com"]}
    def rdap_lookup(domain):
        queries.append(("rdap", domain))
        return sample_data["rdap"]
    monkeypatch.setattr(inv, "dns_lookup", dns_lookup)
    monkeypatch.setattr(inv, "rdap_lookup", rdap_lookup)
    monkeypatch.setattr(inv, "fetch_page", lambda url: {"ok": True, "status_code": 200, "final_url": url, "headers": {"cf-ray": "example"}, "html": "", "error": None})
    data = inv.investigate("https://store.example.com/product", inv.BrandInfo(), tmp_path)
    assert queries == [("dns", "store.example.com"), ("rdap", "example.com")]
    assert data["detected"]["hosting"]["provider"] == "Shopify"


@pytest.mark.parametrize("status", [200, 404, 503])
def test_fetch_page_retains_html_and_records_http_errors(monkeypatch, status):
    calls = []
    def get(url, **kwargs):
        calls.append(kwargs)
        return types.SimpleNamespace(status_code=status, url=url, headers={"Server": "example"}, text="<html>Evidence</html>")
    monkeypatch.setattr(inv.requests, "get", get)
    page = inv.fetch_page("https://example.com/product")
    assert page["status_code"] == status
    assert page["html"] == "<html>Evidence</html>"
    assert bool(page["error"]) == (status >= 400)
    assert calls[0]["headers"]["User-Agent"] == "IndependentSiteIPInvestigator/1.1 (+https://github.com/LuckeeAI/independent-site-ip-investigator)"


def test_fetch_page_network_failure_is_not_ok(monkeypatch):
    def fail(*args, **kwargs):
        raise inv.requests.ConnectionError("connection refused")
    monkeypatch.setattr(inv.requests, "get", fail)
    page = inv.fetch_page("https://example.com")
    assert page["ok"] is False
    assert page["error"] == "connection refused"
    assert page["html"] == ""


def test_rdap_parser_uses_mocked_json(monkeypatch):
    calls = []
    def rdap(url):
        calls.append(url)
        return {"entities": [{"roles": ["registrar"], "vcardArray": ["vcard", [["fn", {}, "text", "Example Registrar"], ["email", {}, "text", "abuse@example.net"]]]}], "nameservers": [{"ldhName": "NS1.EXAMPLE.NET."}]}
    monkeypatch.setattr(inv, "safe_request_json", rdap)
    result = inv.rdap_lookup("example.com")
    assert calls == ["https://rdap.org/domain/example.com"]
    assert result["registrar"] == "Example Registrar"
    assert result["abuse_email"] == "abuse@example.net"
    assert result["nameservers"] == ["ns1.example.net"]


def test_dns_and_ipwhois_use_mocked_clients(monkeypatch):
    def resolve(domain, record_type):
        assert domain == "example.com"
        return {"NS": ["ns1.example.net."], "A": ["192.0.2.10"], "AAAA": [], "CNAME": [], "MX": []}[record_type]
    monkeypatch.setattr(inv.dns.resolver, "resolve", resolve)
    monkeypatch.setattr(inv, "IPWhois", lambda ip: types.SimpleNamespace(lookup_rdap=lambda **kwargs: {"asn": "64500", "asn_description": "Example Host", "network": {"name": "EXAMPLE", "country": "US"}}))
    assert inv.dns_lookup("example.com")["a_records"] == ["192.0.2.10"]
    assert inv.ip_asn_lookup("192.0.2.10")["asn_description"] == "Example Host"
