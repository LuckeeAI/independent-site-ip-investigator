import pytest

import site_ip_investigator as inv


@pytest.fixture
def nested_rdap():
    return {
        "entities": [{
            "roles": ["registrar"],
            "vcardArray": ["vcard", [["fn", {}, "text", "MarkMonitor Inc."]]],
            "publicIds": [{"type": "IANA Registrar ID", "identifier": "292"}],
            "entities": [{
                "roles": ["abuse"],
                "vcardArray": ["vcard", [
                    ["fn", {}, "text", ""],
                    ["tel", {"type": "voice"}, "uri", "tel:+1.2086851750"],
                    ["email", {}, "text", "abusecomplaints@markmonitor.com"],
                ]],
            }],
        }],
    }


@pytest.fixture
def lookup_rdap(monkeypatch):
    def lookup(data):
        monkeypatch.setattr(inv, "safe_request_json", lambda url: data)
        return inv.rdap_lookup("brand-store.com")
    return lookup


def test_nested_verisign_abuse_contact(lookup_rdap, nested_rdap):
    result = lookup_rdap(nested_rdap)
    assert result["registrar"] == "MarkMonitor Inc."
    assert result["abuse_email"] == "abusecomplaints@markmonitor.com"
    assert result["abuse_phone"] == "+1.2086851750"
    assert result["registrar_iana_id"] == "292"
    assert result["complaint_url_guess"] is None


@pytest.mark.parametrize("database_update_first", [False, True])
def test_domain_dates_ignore_rdap_database_refresh(lookup_rdap, database_update_first):
    changed = {"eventAction": "last changed", "eventDate": "2024-04-15T12:30:00Z"}
    refreshed = {
        "eventAction": "last update of RDAP database",
        "eventDate": "2026-11-10T09:00:00Z",
    }
    updates = [refreshed, changed] if database_update_first else [changed, refreshed]
    result = lookup_rdap({"events": [
        {"eventAction": "registration", "eventDate": "2010-06-01T08:00:00Z"},
        *updates,
        {"eventAction": "expiration", "eventDate": "2027-06-01T08:00:00Z"},
    ]})
    assert result["created_date"] == "2010-06-01T08:00:00Z"
    assert result["updated_date"] == "2024-04-15T12:30:00Z"
    assert result["expires_date"] == "2027-06-01T08:00:00Z"


@pytest.mark.parametrize("action", [
    "creation",
    "reregistration",
    "last update",
    "last update of RDAP database",
    "LAST UPDATE OF RDAP DATABASE",
    "expiry",
])
def test_unrecognized_events_do_not_supply_domain_dates(lookup_rdap, action):
    result = lookup_rdap({"events": [{
        "eventAction": action,
        "eventDate": "2026-11-10T09:00:00Z",
    }]})
    assert result["created_date"] is None
    assert result["updated_date"] is None
    assert result["expires_date"] is None


@pytest.mark.parametrize("abuse_first", [False, True])
def test_abuse_role_takes_precedence_regardless_of_entity_order(lookup_rdap, abuse_first):
    registrar = {
        "roles": ["registrar"],
        "vcardArray": ["vcard", [
            ["email", {}, "text", "registrar@example.net"],
            ["tel", {}, "text", "+1.1111111111"],
        ]],
    }
    abuse = {
        "roles": ["abuse"],
        "vcardArray": ["vcard", [
            ["email", {}, "text", "abuse@example.net"],
            ["tel", {}, "uri", "tel:+1.2222222222"],
        ]],
    }
    entities = [abuse, registrar] if abuse_first else [registrar, abuse]
    result = lookup_rdap({"entities": entities})
    assert result["abuse_email"] == "abuse@example.net"
    assert result["abuse_phone"] == "+1.2222222222"


@pytest.mark.parametrize("abuse_rows,expected_email", [
    ([], None),
    ([["email", {}, "text", ""], ["tel", {}, "text", ""]], None),
    ([["email", {}, "text", "abuse@example.net"]], "abuse@example.net"),
])
def test_abuse_entity_blocks_registrar_fallback_even_with_missing_contacts(
    lookup_rdap, abuse_rows, expected_email,
):
    result = lookup_rdap({"entities": [{
        "roles": ["registrar"],
        "vcardArray": ["vcard", [
            ["email", {}, "text", "registrar@example.net"],
            ["tel", {}, "text", "+1.1111111111"],
        ]],
        "entities": [{"roles": ["abuse"], "vcardArray": ["vcard", abuse_rows]}],
    }]})
    assert result["abuse_email"] == expected_email
    assert result["abuse_phone"] is None


def test_deeply_nested_entities_include_contacts_registrar_and_public_ids(lookup_rdap, nested_rdap):
    registrar = nested_rdap["entities"][0]
    registrar["entities"][0]["publicIds"] = registrar.pop("publicIds")
    data = nested_rdap
    for _ in range(5):
        data = {"entities": [data]}
    result = lookup_rdap(data)
    assert result["registrar"] == "MarkMonitor Inc."
    assert result["registrar_iana_id"] == "292"
    assert result["abuse_email"] == "abusecomplaints@markmonitor.com"
    assert result["abuse_phone"] == "+1.2086851750"


@pytest.mark.parametrize("phone_type", ["text", "uri"])
@pytest.mark.parametrize("phone_value", ["tel:+1.2086851750", "+1.2086851750"])
def test_registrar_fallback_normalizes_text_and_uri_phone_values(
    lookup_rdap, phone_type, phone_value,
):
    result = lookup_rdap({"entities": [{
        "roles": ["registrar"],
        "vcardArray": ["vcard", [
            ["email", {}, "text", "registrar@example.net"],
            ["tel", {}, phone_type, phone_value],
        ]],
    }]})
    assert result["abuse_email"] == "registrar@example.net"
    assert result["abuse_phone"] == "+1.2086851750"


def test_empty_vcard_values_do_not_hide_later_values(lookup_rdap):
    result = lookup_rdap({"entities": [{
        "roles": ["registrar"],
        "vcardArray": ["vcard", [
            ["fn", {}, "text", ""],
            ["fn", {}, "text", "Example Registrar"],
            ["email", {}, "text", ""],
            ["email", {}, "text", "registrar@example.net"],
            ["tel", {}, "text", ""],
            ["tel", {}, "text", "tel:+1.2086851750"],
        ]],
    }]})
    assert result["registrar"] == "Example Registrar"
    assert result["abuse_email"] == "registrar@example.net"
    assert result["abuse_phone"] == "+1.2086851750"


def test_empty_registrar_vcard_values_remain_missing(lookup_rdap):
    result = lookup_rdap({"entities": [{
        "roles": ["registrar"],
        "vcardArray": ["vcard", [
            ["fn", {}, "text", ""],
            ["email", {}, "text", ""],
            ["tel", {}, "uri", ""],
        ]],
    }]})
    assert result["registrar"] is None
    assert result["abuse_email"] is None
    assert result["abuse_phone"] is None
