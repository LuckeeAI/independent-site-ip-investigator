#!/usr/bin/env python3
"""
Independent Site IP Investigator

Local MVP for OpenClaw / Hermes Agent skills.
- Single URL/domain investigation
- RDAP, DNS, HTTP headers, HTML fingerprinting, CDN/platform/payment detection
- Optional screenshots via Playwright
- Optional LLM-enhanced Markdown report via OpenAI Responses API
- Optional PDF via markdown2 + WeasyPrint
- CSV batch mode

No automated complaint submission is performed.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime as dt
import html as html_lib
import ipaddress
import json
import os
import re
import socket
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import dns.resolver
import requests
import tldextract
from bs4 import BeautifulSoup
from ipwhois import IPWhois

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

USER_AGENT = "Mozilla/5.0 (compatible; IndependentSiteIPInvestigator/1.0; +brand-enforcement)"
REQUEST_TIMEOUT = 20
MAX_HTML_CHARS = 700_000

PLATFORM_RULES: Dict[str, List[str]] = {
    "Shopify": ["cdn.shopify.com", "myshopify.com", "Shopify.theme", "shopifycloud", "ShopifyAnalytics", "Shopify.routes", "/cart.js"],
    "WooCommerce / WordPress": ["wp-content", "wp-includes", "woocommerce", "wp-json", "wc-cart-fragments", "cart-fragments"],
    "Wix": ["wixstatic.com", "wix.com", "X-Wix", "wix-code", "wixstores"],
    "Squarespace": ["squarespace.com", "static1.squarespace.com", "Y.Squarespace", "squarespace-cdn"],
    "BigCommerce": ["bigcommerce", "mybigcommerce.com", "stencil", "cdn11.bigcommerce.com"],
    "Magento / Adobe Commerce": ["Magento", "mage/", "static/version", "Magento_Theme", "Magento_Customer"],
    "Shopline": ["shoplineapp.com", "shopline", "shoplineimg.com"],
    "Shoplazza": ["shoplazza", "myshoplaza.com", "shoplazza.com"],
    "Shopyy": ["shopyy", "myshopifyy", "ueeshop"],
    "PrestaShop": ["prestashop", "ps_shoppingcart", "modules/ps_"],
    "OpenCart": ["catalog/view/theme", "index.php?route=checkout", "route=product/product"],
}

CDN_RULES: Dict[str, List[str]] = {
    "Cloudflare": ["cloudflare", "cf-ray", "__cf_bm", "cf-cache-status", ".ns.cloudflare.com"],
    "Akamai": ["akamai", "akamaihd", "akamaiedge", "x-akamai"],
    "Fastly": ["fastly", "x-served-by", "x-cache-hits"],
    "Amazon CloudFront": ["cloudfront", "x-amz-cf-id", "x-amz-cf-pop"],
    "Google CDN": ["googleusercontent", "googlesyndication", "gstatic", "google cdn"],
    "BunnyCDN": ["bunnycdn", "b-cdn.net"],
    "Shopify CDN": ["cdn.shopify.com", "shopifycdn"],
    "Vercel Edge": ["vercel", "x-vercel-id", "x-vercel-cache"],
    "Netlify CDN": ["netlify", "x-nf-request-id"],
}

PAYMENT_RULES: Dict[str, List[str]] = {
    "PayPal": ["paypal.com", "paypalobjects.com", "paypal-button", "paypal_sdk"],
    "Stripe": ["stripe.com", "js.stripe.com", "stripe-js", "stripe_payments"],
    "Shop Pay": ["shop.app", "shopify_pay", "shop pay", "shopify-payment-button"],
    "Klarna": ["klarna.com", "klarna"],
    "Afterpay": ["afterpay.com", "afterpay", "clearpay"],
    "Apple Pay": ["apple-pay", "ApplePaySession", "apple pay"],
    "Google Pay": ["googlepay", "Google Pay", "google-pay"],
    "Adyen": ["adyen.com", "adyen"],
    "Sezzle": ["sezzle.com", "sezzle"],
    "Checkout.com": ["checkout.com", "cko-"],
}

REGISTRAR_COMPLAINT_URLS = {
    "namecheap": "https://www.namecheap.com/support/knowledgebase/article.aspx/9196/5/how-and-where-can-i-file-abuse-complaints/",
    "godaddy": "https://supportcenter.godaddy.com/AbuseReport",
    "tucows": "https://tucowsdomains.com/report-abuse/",
    "enom": "https://www.enom.com/report-abuse/",
    "dynadot": "https://www.dynadot.com/report-abuse",
    "porkbun": "https://porkbun.com/abuse",
    "cloudflare": "https://abuse.cloudflare.com/",
    "namesilo": "https://www.namesilo.com/report_abuse.php",
}

SERVICE_COMPLAINT_URLS = {
    "Shopify": "https://www.shopify.com/legal/report-aup-violation",
    "Cloudflare": "https://abuse.cloudflare.com/",
    "Wix": "https://www.wix.com/about/abuse",
    "Squarespace": "https://support.squarespace.com/hc/en-us/articles/360035061952-Reporting-copyright-infringement",
    "BigCommerce": "https://www.bigcommerce.com/legal/report-abuse/",
    "Google Search Removal": "https://reportcontent.google.com/",
}

@dataclasses.dataclass
class BrandInfo:
    brand: str = ""
    company: str = ""
    amazon_url: str = ""
    official_url: str = ""
    infringement: str = "copyright+trademark"
    affects_buybox: str = "yes"


def utc_timestamp() -> str:
    return dt.datetime.utcnow().strftime("%Y%m%d_%H%M%S_UTC")


def normalize_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ValueError("URL/domain is required")
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    return value


def extract_domain(url: str) -> str:
    parsed = urlparse(normalize_url(url))
    host = parsed.hostname or parsed.netloc or url
    ext = tldextract.extract(host)
    if not ext.domain or not ext.suffix:
        return host.lower().strip("/")
    return f"{ext.domain}.{ext.suffix}".lower()


def safe_request_json(url: str) -> Optional[dict]:
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rdap+json, application/json"}, timeout=REQUEST_TIMEOUT)
        if r.status_code >= 400:
            return None
        return r.json()
    except Exception:
        return None


def rdap_lookup(domain: str) -> Dict[str, Any]:
    """Query RDAP via rdap.org and parse registrar/abuse contacts best-effort."""
    rdap_url = f"https://rdap.org/domain/{domain}"
    data = safe_request_json(rdap_url)
    out: Dict[str, Any] = {
        "rdap_url": rdap_url,
        "registrar": None,
        "registrar_iana_id": None,
        "abuse_email": None,
        "abuse_phone": None,
        "created_date": None,
        "updated_date": None,
        "expires_date": None,
        "nameservers": [],
        "raw_available": bool(data),
    }
    if not data:
        out["note"] = "RDAP lookup failed or returned no usable data. Keep DNS nameservers and ICANN/RDAP link for manual review."
        return out

    # Registrar fields vary by registry.
    out["registrar"] = data.get("registrar") or data.get("registrarName")
    for ent in data.get("entities", []) or []:
        roles = [r.lower() for r in ent.get("roles", [])]
        vcard = ent.get("vcardArray")
        if "registrar" in roles and not out["registrar"]:
            out["registrar"] = parse_vcard_fn(vcard)
        # Abuse contact may be an entity role, or nested publicIds.
        if "abuse" in roles or "registrar" in roles:
            email, phone = parse_vcard_contact(vcard)
            if email and not out["abuse_email"]:
                out["abuse_email"] = email
            if phone and not out["abuse_phone"]:
                out["abuse_phone"] = phone
        for pid in ent.get("publicIds", []) or []:
            if str(pid.get("type", "")).lower() in {"iana registrar id", "registrar id"}:
                out["registrar_iana_id"] = pid.get("identifier")

    # Sometimes abuse is in remarks/links or notices, but avoid guessing.
    for event in data.get("events", []) or []:
        action = str(event.get("eventAction", "")).lower()
        date = event.get("eventDate")
        if "registration" in action and not out["created_date"]:
            out["created_date"] = date
        elif "last changed" in action or "last update" in action or "updated" in action:
            out["updated_date"] = date
        elif "expiration" in action or "expiry" in action:
            out["expires_date"] = date

    out["nameservers"] = [ns.get("ldhName", "").lower().rstrip(".") for ns in data.get("nameservers", []) or [] if ns.get("ldhName")]
    out["complaint_url_guess"] = complaint_url_for_registrar(out.get("registrar"))
    return out


def parse_vcard_fn(vcard: Any) -> Optional[str]:
    if not isinstance(vcard, list) or len(vcard) < 2:
        return None
    for row in vcard[1]:
        if isinstance(row, list) and len(row) >= 4 and row[0] == "fn":
            return row[3]
    return None


def parse_vcard_contact(vcard: Any) -> Tuple[Optional[str], Optional[str]]:
    email = None
    phone = None
    if not isinstance(vcard, list) or len(vcard) < 2:
        return None, None
    for row in vcard[1]:
        if not isinstance(row, list) or len(row) < 4:
            continue
        kind = row[0]
        value = row[3]
        if kind == "email" and not email:
            email = value
        if kind == "tel" and not phone:
            phone = value
    return email, phone


def complaint_url_for_registrar(registrar: Optional[str]) -> Optional[str]:
    if not registrar:
        return None
    low = registrar.lower()
    for key, url in REGISTRAR_COMPLAINT_URLS.items():
        if key in low:
            return url
    return None


def dns_lookup(domain: str) -> Dict[str, Any]:
    result = {"nameservers": [], "a_records": [], "aaaa_records": [], "cname_records": [], "mx_records": [], "errors": {}}
    for rtype, key in [("NS", "nameservers"), ("A", "a_records"), ("AAAA", "aaaa_records"), ("CNAME", "cname_records"), ("MX", "mx_records")]:
        try:
            answers = dns.resolver.resolve(domain, rtype)
            vals = []
            for r in answers:
                vals.append(str(r).rstrip("."))
            result[key] = vals
        except Exception as e:
            result["errors"][rtype] = str(e)
    return result


def fetch_page(url: str) -> Dict[str, Any]:
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        return {
            "ok": True,
            "status_code": r.status_code,
            "final_url": r.url,
            "headers": dict(r.headers),
            "html": r.text[:MAX_HTML_CHARS],
            "error": None,
        }
    except Exception as e:
        return {"ok": False, "status_code": None, "final_url": None, "headers": {}, "html": "", "error": str(e)}


def detect_by_rules(text: str, rules: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    text_low = (text or "").lower()
    found = []
    for name, keywords in rules.items():
        matches = [kw for kw in keywords if kw.lower() in text_low]
        if matches:
            found.append({
                "name": name,
                "matched_keywords": matches,
                "confidence": "high" if len(matches) >= 2 else "medium",
            })
    return sorted(found, key=lambda x: (x["confidence"] != "high", x["name"]))


def combined_signal_text(dns_data: dict, page: dict) -> str:
    parts = []
    for key in ["nameservers", "a_records", "aaaa_records", "cname_records", "mx_records"]:
        parts.extend(dns_data.get(key, []))
    headers = page.get("headers", {}) or {}
    parts.extend([f"{k}: {v}" for k, v in headers.items()])
    parts.append(page.get("html", "")[:200_000])
    return "\n".join(parts)


def ip_asn_lookup(ip: str) -> Dict[str, Any]:
    try:
        ipaddress.ip_address(ip)
        data = IPWhois(ip).lookup_rdap(depth=1)
        return {
            "ip": ip,
            "asn": data.get("asn"),
            "asn_description": data.get("asn_description"),
            "network_name": (data.get("network") or {}).get("name"),
            "country": (data.get("network") or {}).get("country"),
        }
    except Exception as e:
        return {"ip": ip, "error": str(e)}


def visible_hosting(dns_data: dict, cdn_detected: list) -> Dict[str, Any]:
    cdn_names = {d["name"] for d in cdn_detected}
    if "Cloudflare" in cdn_names:
        return {"status": "hidden_by_cloudflare", "note": "Cloudflare detected; real origin hosting provider is likely hidden from public DNS/HTTP data."}
    a_records = dns_data.get("a_records", [])
    if not a_records:
        return {"status": "unknown", "note": "No A records found in basic DNS lookup."}
    return {"status": "visible", "asn": ip_asn_lookup(a_records[0])}


def screenshot_page(url: str, out_dir: Path) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {"enabled": True, "files": [], "error": None}
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1365, "height": 1800}, user_agent=USER_AGENT)
            page.goto(url, wait_until="networkidle", timeout=45_000)
            full = out_dir / "page_full.png"
            page.screenshot(path=str(full), full_page=True)
            result["files"].append(str(full))
            browser.close()
    except Exception as e:
        result["error"] = str(e)
    return result


def build_priority(platforms: list, cdns: list, hosting: dict, registrar: dict) -> List[Dict[str, str]]:
    priority = []
    platform_names = [p["name"] for p in platforms]
    cdn_names = [c["name"] for c in cdns]

    for p in platforms:
        if p["name"] in SERVICE_COMPLAINT_URLS or p["confidence"] in {"high", "medium"}:
            priority.append({"target": p["name"], "reason": f"Likely ecommerce/site platform ({p['confidence']} confidence); it may control product pages or storefront content.", "url": SERVICE_COMPLAINT_URLS.get(p["name"], "")})
            break

    for c in cdns:
        if c["name"] == "Cloudflare":
            priority.append({"target": "Cloudflare", "reason": "Cloudflare/CDN detected; submit abuse/DMCA/trademark report in parallel. It may forward to host/operator.", "url": SERVICE_COMPLAINT_URLS["Cloudflare"]})
            break

    if hosting.get("status") == "visible":
        asn = hosting.get("asn", {})
        desc = asn.get("asn_description") or asn.get("network_name") or "visible hosting ASN"
        priority.append({"target": desc, "reason": "Origin/hosting ASN appears visible; host may be able to disable infringing content.", "url": ""})

    reg_name = registrar.get("registrar") or "Domain registrar"
    priority.append({"target": reg_name, "reason": "Registrar abuse contact is useful for trademark impersonation, fake-store, phishing, repeated abuse, or if platform/host does not act.", "url": registrar.get("complaint_url_guess") or registrar.get("rdap_url") or ""})
    priority.append({"target": "Google Search Removal", "reason": "If the page remains live or indexed, request search-result removal to reduce visibility.", "url": SERVICE_COMPLAINT_URLS["Google Search Removal"]})
    return priority


def investigate(url: str, brand_info: BrandInfo, out_dir: Path, do_screenshots: bool = False) -> Dict[str, Any]:
    url = normalize_url(url)
    domain = extract_domain(url)
    page = fetch_page(url)
    dns_data = dns_lookup(domain)
    rdap = rdap_lookup(domain)

    # Merge RDAP nameservers if DNS NS failed.
    if not dns_data.get("nameservers") and rdap.get("nameservers"):
        dns_data["nameservers"] = rdap["nameservers"]

    signal = combined_signal_text(dns_data, page)
    platforms = detect_by_rules(page.get("html", ""), PLATFORM_RULES)
    cdns = detect_by_rules(signal, CDN_RULES)
    payments = detect_by_rules(signal, PAYMENT_RULES)
    hosting = visible_hosting(dns_data, cdns)

    screenshots = {"enabled": False, "files": [], "error": None}
    if do_screenshots:
        screenshots = screenshot_page(page.get("final_url") or url, out_dir / "screenshots")

    data = {
        "generated_at_utc": dt.datetime.utcnow().isoformat() + "Z",
        "input_url": url,
        "domain": domain,
        "brand_info": dataclasses.asdict(brand_info),
        "rdap": rdap,
        "dns": dns_data,
        "http": {
            "ok": page.get("ok"),
            "status_code": page.get("status_code"),
            "final_url": page.get("final_url"),
            "headers": page.get("headers"),
            "error": page.get("error"),
        },
        "detected": {
            "platforms": platforms,
            "cdn": cdns,
            "payments_possible": payments,
            "hosting": hosting,
        },
        "complaint_priority": build_priority(platforms, cdns, hosting, rdap),
        "screenshots": screenshots,
    }
    return data


def md_escape(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|")


def deterministic_report(data: Dict[str, Any]) -> str:
    brand = data.get("brand_info", {})
    detected = data.get("detected", {})
    rdap = data.get("rdap", {})
    dns_data = data.get("dns", {})
    http = data.get("http", {})
    domain = data.get("domain", "")

    def det_list(items: list) -> str:
        if not items:
            return "- 未检测到明确特征。\n"
        return "".join([f"- {i['name']}（可信度：{i['confidence']}；依据：{', '.join(i['matched_keywords'])}）\n" for i in items])

    screenshot_lines = ""
    for f in data.get("screenshots", {}).get("files", []) or []:
        screenshot_lines += f"- {f}\n"
    if not screenshot_lines:
        screenshot_lines = "- 未生成截图，或截图失败。\n"

    priority_lines = ""
    for idx, p in enumerate(data.get("complaint_priority", []), start=1):
        url = f"；入口：{p.get('url')}" if p.get("url") else ""
        priority_lines += f"{idx}. **{p.get('target')}**：{p.get('reason')}{url}\n"

    infringement = (brand.get("infringement") or "").lower()
    needs_dmca = "copyright" in infringement or "盗图" in infringement or "image" in infringement
    needs_tm = "trademark" in infringement or "商标" in infringement or "brand" in infringement

    dmca = dmca_template(brand, domain) if needs_dmca else "不适用：用户未选择盗图 / copyright 侵权类型。"
    tm = trademark_template(brand, domain) if needs_tm else "不适用：用户未选择商标 / trademark 侵权类型。"
    amazon = amazon_case_template(brand, domain)

    return f"""# 独立站侵权调查报告

生成时间：{data.get('generated_at_utc')}

## 1. 基础信息

- 目标域名：{domain}
- 输入 URL：{data.get('input_url')}
- 最终访问 URL：{http.get('final_url')}
- HTTP 状态：{http.get('status_code')}
- 品牌：{brand.get('brand')}
- 公司：{brand.get('company')}
- 侵权类型：{brand.get('infringement')}
- 是否影响 Amazon Buy Box：{brand.get('affects_buybox')}

## 2. 域名注册商 / RDAP

- Registrar：{rdap.get('registrar') or '未检测到'}
- Registrar IANA ID：{rdap.get('registrar_iana_id') or '未检测到'}
- Abuse Email：{rdap.get('abuse_email') or '未检测到'}
- Abuse Phone：{rdap.get('abuse_phone') or '未检测到'}
- Created：{rdap.get('created_date') or '未检测到'}
- Updated：{rdap.get('updated_date') or '未检测到'}
- RDAP URL：{rdap.get('rdap_url')}
- Registrar Complaint URL：{rdap.get('complaint_url_guess') or '未检测到，可使用 registrar abuse email 或 RDAP/ICANN 结果人工查询'}

## 3. DNS / Name Server

- Name Server：{', '.join(dns_data.get('nameservers') or []) or '未检测到'}
- A Records：{', '.join(dns_data.get('a_records') or []) or '未检测到'}
- CNAME Records：{', '.join(dns_data.get('cname_records') or []) or '未检测到'}

## 4. 服务商识别结果

### 建站平台
{det_list(detected.get('platforms') or [])}

### CDN / 代理
{det_list(detected.get('cdn') or [])}

### 主机服务商

```json
{json.dumps(detected.get('hosting'), ensure_ascii=False, indent=2)}
```

### 可能的支付服务商
{det_list(detected.get('payments_possible') or [])}

## 5. 截图证据
{screenshot_lines}

## 6. 建议投诉优先级
{priority_lines}

## 7. 建议准备的证据材料

- 商标证书 / 品牌备案证明
- GS1 证书，如有
- 原始产品图片、拍摄源文件或官网原图链接
- Amazon listing 链接：{brand.get('amazon_url') or '[填写]'}
- 官网 / 原始图片来源：{brand.get('official_url') or '[填写]'}
- 侵权页面截图和完整页面截图
- 图片对比图：左侧原图，右侧侵权图
- 对方页面价格截图，尤其是影响 Amazon Buy Box 时
- 平台投诉编号和下架回复，后续用于 Amazon case

## 8. 英文 Copyright / DMCA 投诉模板

{dmca}

## 9. 英文 Trademark 投诉模板

{tm}

## 10. Amazon Buy Box / Featured Offer Case 模板

{amazon}

## 11. 注意事项

- 本报告基于公开 DNS、RDAP、HTTP header 和网页源码特征生成。
- 如果检测到 Cloudflare，真实源站主机通常无法从公开数据确认，不应猜测。
- 支付服务商检测仅代表页面源码或资源中出现相关线索，结账页可能需要人工复核。
- 投诉提交前，请确认你是权利人或授权代表。
"""


def dmca_template(brand: dict, domain: str) -> str:
    return f"""Subject: DMCA Copyright Infringement Notice – Unauthorized Use of Product Images

Dear Legal / Abuse Team,

We are submitting this notice to report copyright infringement on the website below:

Infringing Website / Domain: {domain}
Infringing Page URL: [Insert infringing page URL]

We are the copyright owner or authorized representative of the copyrighted product images and listing content used for our brand {brand.get('brand') or '[Brand Name]'} and related products.

The website listed above is using our copyrighted product images and/or listing content without authorization. These images were originally created, owned, and used by our company on our official sales channels, including our Amazon listing and official website.

Original Amazon Listing URL: {brand.get('amazon_url') or '[Insert Amazon listing URL]'}
Official Website / Original Image Source URL: {brand.get('official_url') or '[Insert official website or original image URL]'}

We have not authorized the website owner, operator, or seller to use our copyrighted images, listing content, brand materials, or product photos.

The unauthorized use of our copyrighted materials may mislead consumers and damage our brand reputation. It may also cause incorrect external price matching issues on Amazon and affect our Buy Box / Featured Offer eligibility.

We respectfully request that you remove or disable access to the infringing content as soon as possible.

Attached are supporting documents:
1. Original product images
2. Screenshots of our original Amazon listing
3. Screenshots of our official website or original image source
4. Screenshots of the infringing website
5. Image comparison showing unauthorized use
6. Trademark registration certificate, if applicable
7. Company information and proof of ownership

Rights Owner Information:
Brand Name: {brand.get('brand') or '[Brand Name]'}
Company Name: {brand.get('company') or '[Company Name]'}
Contact Person: [Name]
Email: [Email]
Phone: [Phone]
Address: [Company Address]
Official Website: {brand.get('official_url') or '[Website]'}

I declare under penalty of perjury that the information in this notice is accurate and that I am the copyright owner or authorized representative of the copyright owner. I have a good faith belief that the use of the copyrighted materials described above is not authorized by the copyright owner, its agent, or the law.

Sincerely,
[Name]
[Title]
{brand.get('company') or '[Company Name]'}
"""


def trademark_template(brand: dict, domain: str) -> str:
    return f"""Subject: Trademark Infringement Complaint – Unauthorized Use of Brand Name / Logo

Dear Legal / Abuse Team,

We are writing to report trademark infringement on the following website:

Infringing Website / Domain: {domain}
Infringing Page URL: [Insert infringing page URL]

We are the owner or authorized representative of the registered trademark {brand.get('brand') or '[Brand Name]'}.

The website listed above is using our trademark, brand name, logo, and/or brand materials without authorization. The website is not affiliated with our company, not authorized by our brand, and not approved to represent or sell products under our trademark.

The unauthorized use of our trademark may mislead consumers into believing that the website is operated by, affiliated with, or endorsed by our brand. This creates consumer confusion and damages our brand reputation.

We respectfully request that you remove or disable access to the infringing content, including unauthorized use of our brand name, logo, and trademarked materials.

Attached are supporting documents:
1. Trademark registration certificate
2. Screenshots of the infringing website
3. Screenshots showing unauthorized use of our trademark / logo
4. Screenshots of our official website / Amazon Store
5. Company information and proof of ownership

Rights Owner Information:
Brand Name: {brand.get('brand') or '[Brand Name]'}
Company Name: {brand.get('company') or '[Company Name]'}
Contact Person: [Name]
Email: [Email]
Phone: [Phone]
Address: [Company Address]
Official Website: {brand.get('official_url') or '[Website]'}

I confirm that the information provided in this complaint is accurate and that I am the trademark owner or authorized representative of the trademark owner.

Sincerely,
[Name]
[Title]
{brand.get('company') or '[Company Name]'}
"""


def amazon_case_template(brand: dict, domain: str) -> str:
    return f"""Subject: Request to Remove Incorrect External Price Match and Restore Featured Offer Eligibility

Dear Amazon Seller Support Team,

Our ASIN / listing has lost or may lose Featured Offer eligibility due to an incorrect external price match.

After investigation, we found that Amazon may have matched our product with an unauthorized external website: {domain}. This external website copied our copyrighted product images and/or misused our brand materials without authorization.

This external website is not operated by our company, not authorized by our brand, and should not be treated as a comparable authorized offer for our Amazon listing.

Brand: {brand.get('brand') or '[Brand Name]'}
Company: {brand.get('company') or '[Company Name]'}
Amazon Listing URL: {brand.get('amazon_url') or '[Amazon Listing URL]'}
External Website: {domain}
Official Website / Original Image Source: {brand.get('official_url') or '[Official Website / Original Image Source]'}

We respectfully request Amazon to:
1. Remove the incorrect external price association.
2. Refresh the competitive price data for our ASIN.
3. Re-evaluate Featured Offer eligibility.
4. Restore the Buy Box / Featured Offer if it was removed due to this incorrect external match.

Attached are supporting documents:
1. Brand ownership proof / Amazon Brand Registry proof
2. Original product images
3. Screenshots of our Amazon listing
4. Screenshots of the unauthorized external website
5. Image comparison showing unauthorized use
6. IP complaint submission or takedown confirmation, if available
7. Explanation showing that the external website is unauthorized and not a comparable offer

Thank you for your support.

Best regards,
[Name]
{brand.get('company') or '[Company Name]'}
"""


def llm_report(data: Dict[str, Any]) -> Optional[str]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        model = os.getenv("OPENAI_MODEL", "gpt-5.5")
        prompt = f"""
你是跨境电商品牌维权助手。请根据以下 JSON 生成一份中文调查报告，并附英文 Copyright/DMCA、Trademark、Amazon Buy Box case 模板。

严格要求：
- 不要编造 JSON 中没有的信息。
- 不确定的服务商必须标注“疑似”。
- 如果 hosting.status 是 hidden_by_cloudflare，不要猜真实主机。
- 输出结构必须包括：基础信息、服务商识别、证据说明、投诉优先级、证据清单、英文投诉模板、Amazon case 模板。

JSON:
{json.dumps(data, ensure_ascii=False, indent=2)}
"""
        resp = client.responses.create(
            model=model,
            instructions="You produce careful, non-fabricated brand/IP enforcement reports for ecommerce sellers.",
            input=prompt,
        )
        return getattr(resp, "output_text", None) or str(resp)
    except Exception as e:
        return f"LLM report generation failed: {e}\n\n" + deterministic_report(data)


def write_pdf(markdown_text: str, pdf_path: Path) -> Tuple[bool, Optional[str]]:
    try:
        import markdown2
        from weasyprint import HTML
        body = markdown2.markdown(markdown_text, extras=["tables", "fenced-code-blocks"])
        html = f"""
<html><head><meta charset='utf-8'>
<style>
body {{ font-family: Arial, sans-serif; line-height: 1.45; margin: 32px; }}
h1, h2, h3 {{ color: #222; }}
code, pre {{ background: #f5f5f5; padding: 2px 4px; }}
pre {{ padding: 10px; overflow-wrap: break-word; white-space: pre-wrap; }}
</style></head><body>{body}</body></html>
"""
        HTML(string=html).write_pdf(str(pdf_path))
        return True, None
    except Exception as e:
        return False, str(e)


def save_single_report(data: Dict[str, Any], out_dir: Path, use_llm: bool, make_pdf: bool) -> Dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "investigation.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    report = llm_report(data) if use_llm else None
    if not report:
        report = deterministic_report(data)
    md_path = out_dir / "report.md"
    md_path.write_text(report, encoding="utf-8")
    paths = {"json": str(json_path), "markdown": str(md_path)}
    if make_pdf:
        pdf_path = out_dir / "report.pdf"
        ok, err = write_pdf(report, pdf_path)
        if ok:
            paths["pdf"] = str(pdf_path)
        else:
            paths["pdf_error"] = err or "unknown PDF error"
    return paths


def single_mode(args: argparse.Namespace) -> int:
    brand = BrandInfo(
        brand=args.brand or "",
        company=args.company or "",
        amazon_url=args.amazon_url or "",
        official_url=args.official_url or "",
        infringement=args.infringement or "copyright+trademark",
        affects_buybox=args.affects_buybox or "yes",
    )
    domain = extract_domain(args.url)
    root = Path(args.output_dir or "reports") / f"{domain.replace('.', '_')}_{utc_timestamp()}"
    data = investigate(args.url, brand, root, do_screenshots=args.screenshots)
    paths = save_single_report(data, root, use_llm=not args.no_llm, make_pdf=args.pdf)
    print(json.dumps({"output_dir": str(root), "paths": paths, "summary": summarize_for_console(data)}, ensure_ascii=False, indent=2))
    return 0


def summarize_for_console(data: Dict[str, Any]) -> Dict[str, Any]:
    det = data.get("detected", {})
    return {
        "domain": data.get("domain"),
        "registrar": data.get("rdap", {}).get("registrar"),
        "abuse_email": data.get("rdap", {}).get("abuse_email"),
        "cdn": [x.get("name") for x in det.get("cdn", [])],
        "platform": [x.get("name") for x in det.get("platforms", [])],
        "hosting_status": det.get("hosting", {}).get("status"),
    }


def batch_mode(args: argparse.Namespace) -> int:
    batch_root = Path(args.output_dir or "reports") / f"batch_{utc_timestamp()}"
    batch_root.mkdir(parents=True, exist_ok=True)
    rows_out = []
    with open(args.csv, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader, start=1):
            url = row.get("url") or row.get("URL") or row.get("domain") or row.get("Domain")
            if not url:
                continue
            brand = BrandInfo(
                brand=row.get("brand", ""),
                company=row.get("company", ""),
                amazon_url=row.get("amazon_url", ""),
                official_url=row.get("official_url", ""),
                infringement=row.get("infringement", "copyright+trademark"),
                affects_buybox=row.get("affects_buybox", "yes"),
            )
            domain = extract_domain(url)
            out_dir = batch_root / f"{idx:03d}_{domain.replace('.', '_')}"
            data = investigate(url, brand, out_dir, do_screenshots=args.screenshots)
            paths = save_single_report(data, out_dir, use_llm=not args.no_llm, make_pdf=args.pdf)
            summary = summarize_for_console(data)
            rows_out.append({**summary, "output_dir": str(out_dir), "report_md": paths.get("markdown"), "report_pdf": paths.get("pdf", "")})
            print(json.dumps(rows_out[-1], ensure_ascii=False))

    summary_csv = batch_root / "batch_summary.csv"
    if rows_out:
        with summary_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
            writer.writeheader()
            writer.writerows(rows_out)
    summary_md = batch_root / "batch_summary.md"
    summary_md.write_text(batch_summary_markdown(rows_out), encoding="utf-8")
    print(json.dumps({"batch_output_dir": str(batch_root), "summary_csv": str(summary_csv), "summary_md": str(summary_md)}, ensure_ascii=False, indent=2))
    return 0


def batch_summary_markdown(rows: List[Dict[str, Any]]) -> str:
    total = len(rows)
    shopify = sum(1 for r in rows if "Shopify" in (r.get("platform") or []))
    cf = sum(1 for r in rows if "Cloudflare" in (r.get("cdn") or []))
    hidden = sum(1 for r in rows if r.get("hosting_status") == "hidden_by_cloudflare")
    lines = [
        "# Batch Investigation Summary",
        "",
        f"- Total sites: {total}",
        f"- Shopify detected: {shopify}",
        f"- Cloudflare detected: {cf}",
        f"- Hosting hidden by Cloudflare: {hidden}",
        "",
        "| Domain | Registrar | Abuse Email | Platform | CDN | Hosting | Report |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {md_escape(r.get('domain'))} | {md_escape(r.get('registrar'))} | {md_escape(r.get('abuse_email'))} | {md_escape(', '.join(r.get('platform') or []))} | {md_escape(', '.join(r.get('cdn') or []))} | {md_escape(r.get('hosting_status'))} | {md_escape(r.get('report_md'))} |")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Independent Site IP Investigator for brand/IP enforcement.")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--url", help="Target infringing URL or domain")
    group.add_argument("--csv", help="Batch CSV path. Required columns: url; optional: brand,company,amazon_url,official_url,infringement,affects_buybox")
    p.add_argument("--brand", default="", help="Brand name")
    p.add_argument("--company", default="", help="Company name")
    p.add_argument("--amazon-url", default="", help="Amazon listing URL")
    p.add_argument("--official-url", default="", help="Official site / original image source URL")
    p.add_argument("--infringement", default="copyright+trademark", help="copyright, trademark, or copyright+trademark")
    p.add_argument("--affects-buybox", default="yes", help="yes/no")
    p.add_argument("--screenshots", action="store_true", help="Capture full-page screenshot via Playwright")
    p.add_argument("--pdf", action="store_true", help="Generate PDF report if dependencies are available")
    p.add_argument("--no-llm", action="store_true", help="Disable OpenAI report generation even if OPENAI_API_KEY is set")
    p.add_argument("--output-dir", default="reports", help="Output root directory")
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.csv:
            return batch_mode(args)
        return single_mode(args)
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
