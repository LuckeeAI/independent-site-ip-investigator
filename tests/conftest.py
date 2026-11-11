"""Offline fixtures shared by the CLI and investigation regression tests."""

import copy
import socket
import sys
from pathlib import Path

import pytest
import tldextract

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import site_ip_investigator as investigator


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("Unexpected network access in an offline test")

    monkeypatch.setattr(investigator.requests, "get", blocked)
    monkeypatch.setattr(investigator.dns.resolver, "resolve", blocked)
    monkeypatch.setattr(investigator, "IPWhois", blocked)
    monkeypatch.setattr(investigator, "safe_request_json", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(
        investigator.tldextract,
        "extract",
        tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None),
    )
    for name in ("OPENAI_API_KEY", "OPENAI_MODEL", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def sample_data():
    return {
        "generated_at_utc": "2026-11-09T10:00:00+00:00",
        "input_url": "https://example.com/products/original?variant=1",
        "domain": "example.com",
        "brand_info": {
            "brand": "Example Brand",
            "company": "Example Company",
            "amazon_url": "https://example.org/listing",
            "official_url": "https://example.org",
            "infringement": "copyright+trademark",
            "affects_buybox": "yes",
        },
        "rdap": {
            "registrar": "Example Registrar",
            "rdap_url": "https://rdap.org/domain/example.com",
            "nameservers": [],
        },
        "dns": {
            "nameservers": ["ns1.example.net"],
            "a_records": ["192.0.2.5"],
            "aaaa_records": [],
            "cname_records": [],
            "mx_records": [],
            "errors": {},
        },
        "http": {
            "ok": True,
            "status_code": 200,
            "final_url": "https://example.com/products/final?variant=1",
            "headers": {},
            "error": None,
        },
        "detected": {
            "platforms": [],
            "cdn": [],
            "payments_possible": [],
            "hosting": {"status": "unknown"},
        },
        "complaint_priority": [],
        "screenshots": {"enabled": False, "files": [], "error": None},
    }


@pytest.fixture
def run_investigation(monkeypatch, tmp_path, sample_data):
    """Exercise orchestration while replacing each external lookup boundary."""
    def run(*, html="", headers=None, dns=None, url="https://example.com/product"):
        dns_data = copy.deepcopy(sample_data["dns"])
        dns_data.update(dns or {})
        page = {
            "ok": True,
            "status_code": 200,
            "final_url": url,
            "headers": headers or {},
            "html": html,
            "error": None,
        }
        monkeypatch.setattr(investigator, "fetch_page", lambda target: page)
        monkeypatch.setattr(investigator, "dns_lookup", lambda domain: dns_data)
        monkeypatch.setattr(investigator, "rdap_lookup", lambda domain: copy.deepcopy(sample_data["rdap"]))
        monkeypatch.setattr(investigator, "ip_asn_lookup", lambda ip: {"ip": ip, "asn_description": "Example Host"})
        return investigator.investigate(url, investigator.BrandInfo(), tmp_path)

    return run
