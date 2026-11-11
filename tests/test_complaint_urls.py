import pytest

import site_ip_investigator as inv


@pytest.mark.parametrize("registrar,expected_url", [
    ("NameCheap, Inc.", "https://www.namecheap.com/support/knowledgebase/article.aspx/9196/5/how-and-where-can-i-file-abuse-complaints/"),
    ("GoDaddy.com, LLC", "https://legalportal.godaddy.com/abuse/ipclaims"),
    ("Tucows Domains Inc.", "https://tucowsdomains.com/report-abuse/"),
    ("eNom, LLC", "https://support.enom.com/support/solutions/articles/201000130069-report-domain-abuse-to-enom"),
    ("Dynadot Inc", "https://www.dynadot.com/report-abuse"),
    ("Porkbun LLC", "https://porkbun.com/abuse"),
    ("Cloudflare, Inc.", "https://abuse.cloudflare.com/"),
    ("NameSilo, LLC", "https://www.namesilo.com/report_abuse.php"),
    ("MarkMonitor Inc.", None),
])
def test_registrar_complaint_urls_verified_2026_11_10(registrar, expected_url):
    assert inv.complaint_url_for_registrar(registrar) == expected_url


@pytest.mark.parametrize("service,expected_url", [
    ("Shopify", "https://www.shopify.com/legal/tools/report-an-issue"),
    ("Cloudflare", "https://abuse.cloudflare.com/"),
    ("Wix", "https://www.wix.com/abuse"),
    ("Squarespace", "https://support.squarespace.com/hc/en-us/articles/360002109308-Intellectual-property-and-Squarespace"),
    ("BigCommerce", "https://www.bigcommerce.com/dmca-form/"),
    ("Google Search Removal", "https://reportcontent.google.com/"),
])
def test_priority_complaint_urls_verified_2026_11_10(service, expected_url):
    platforms = []
    cdn = []
    if service == "Cloudflare":
        cdn = [{"name": service, "confidence": "high"}]
    elif service != "Google Search Removal":
        platforms = [{"name": service, "confidence": "high"}]
    priority = inv.build_priority(platforms, cdn, {"status": "unknown"}, {})
    target = next(item for item in priority if item["target"] == service)
    assert target["url"] == expected_url
