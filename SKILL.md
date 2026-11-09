---
name: independent-site-ip-investigator
description: Investigate an allegedly infringing independent ecommerce site for Amazon sellers. Given a product URL or domain, identify registrar/RDAP abuse contacts, nameservers, CDN, likely ecommerce platform, visible hosting/ASN, possible payment providers, capture screenshots, support CSV batch runs, and generate Markdown/PDF reports plus DMCA, trademark, and Amazon Buy Box case drafts. Use for brand/IP enforcement, stolen product images, trademark misuse, fake stores, or external low-price pages affecting Amazon Featured Offer eligibility.
version: 1.0.0
platforms: [macos, linux]
metadata:
  hermes:
    tags: [python, ecommerce, ip, dmca, amazon, investigation]
    category: research
    requires_toolsets: [terminal]
  openclaw:
    tags: [python, ecommerce, ip, dmca, amazon, investigation]
    requires:
      anyBins: [python3]
---

# Independent Site IP Investigator

Use this skill when the user provides an independent-store URL/domain and wants to identify the website’s registrar, CDN, likely storefront platform, hosting provider, abuse contacts, screenshots, and complaint path for image/copyright or trademark misuse.

This skill is designed for Amazon sellers dealing with stolen product images, trademark misuse, fake independent stores, or external low-price pages that may trigger incorrect Amazon price matching / Buy Box loss.

## What This Skill Does

Given a URL or domain, run the local investigator script to produce:

- Domain registrar via RDAP, when available
- Registrar abuse email / phone, when available
- Nameservers and DNS records
- CDN detection: Cloudflare, Akamai, Fastly, CloudFront, Shopify CDN, BunnyCDN, etc.
- Likely ecommerce platform: Shopify, WooCommerce/WordPress, Wix, Squarespace, BigCommerce, Magento, Shopline, Shoplazza, Shopyy, etc.
- Visible hosting / ASN provider, unless hidden by Cloudflare or another proxy
- Possible payment providers from page/source clues: PayPal, Stripe, Shop Pay, Klarna, Afterpay, Apple Pay, Google Pay, Adyen, etc.
- Screenshots, if Playwright is installed
- Markdown and optional PDF report
- Optional LLM-enhanced report using `OPENAI_API_KEY`
- CSV batch detection and batch summary

## Safety and Accuracy Rules

- Do not claim a service provider is confirmed unless the script output says confidence is `high` or the evidence is explicit.
- If hosting is hidden by Cloudflare or another proxy, say “real origin host cannot be confirmed from public DNS/HTTP data.” Do not guess.
- Payment provider detection is often “possible” only; many sites load payment scripts only after cart/checkout.
- Do not submit legal complaints automatically. Generate evidence and templates only; the user must review and submit.
- For DMCA/trademark complaints, remind the user to verify they are the rights owner or authorized representative before submitting.
- Do not fabricate abuse emails, registrar details, complaint URLs, or screenshot evidence.

## Setup

From the skill folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

For screenshots:

```bash
python -m playwright install chromium
```

For optional OpenAI-generated reports, set:

```bash
export OPENAI_API_KEY="your_api_key"
export OPENAI_MODEL="gpt-5.5"
```

If `OPENAI_API_KEY` is missing, the script still generates structured JSON and a deterministic Markdown report.

## Single-URL Procedure

Run:

```bash
python scripts/site_ip_investigator.py \
  --url "https://example-store.com/products/abc" \
  --brand "Brand Name" \
  --company "Company Name LLC" \
  --amazon-url "https://www.amazon.com/dp/B0XXXXXXX" \
  --official-url "https://brand.com/products/abc" \
  --infringement "copyright+trademark" \
  --affects-buybox yes \
  --screenshots \
  --pdf
```

Expected outputs under `reports/<domain>_<timestamp>/`:

- `investigation.json` — raw structured evidence
- `report.md` — human-readable report
- `report.pdf` — optional PDF if PDF dependencies are available
- `screenshots/homepage.png` and/or `screenshots/page_full.png` when screenshotting succeeds

## Batch Procedure

Prepare a CSV:

```csv
url,brand,company,amazon_url,official_url,infringement,affects_buybox
https://site1.com/products/a,ABC,ABC LLC,https://amazon.com/dp/B0XXX,https://abc.com/a,copyright+trademark,yes
https://site2.com/products/b,ABC,ABC LLC,https://amazon.com/dp/B0YYY,https://abc.com/b,copyright,yes
```

Run:

```bash
python scripts/site_ip_investigator.py --csv input.csv --screenshots --pdf
```

Outputs:

- One report folder per site
- `reports/batch_<timestamp>/batch_summary.csv`
- `reports/batch_<timestamp>/batch_summary.md`
- Optional LLM-generated batch summary if `OPENAI_API_KEY` is set

## Interpreting Results

### Complaint priority logic

Use this default order:

1. Ecommerce platform, if detected with high/medium confidence, e.g. Shopify, Wix, BigCommerce.
2. CDN / reverse proxy, especially Cloudflare, as a parallel complaint path.
3. Hosting provider, if visible and not hidden by Cloudflare/proxy.
4. Registrar abuse contact, especially for trademark impersonation, fake-store, phishing, or repeated abuse.
5. Google Search removal, if the page remains live or indexed.
6. Amazon case, if the external site affects Buy Box / Featured Offer eligibility.

### Recommended language for Amazon Buy Box cases

Emphasize:

- The external page is unauthorized.
- It copied copyrighted product images and/or misused the brand trademark.
- The external page is not a comparable authorized offer.
- Amazon should remove the incorrect external price association and refresh competitive price data.

## Common Failure Modes

- `playwright not installed`: rerun without `--screenshots` or install Playwright and Chromium.
- PDF generation fails: keep the Markdown report; install `markdown2` and `weasyprint` if a PDF is required.
- RDAP returns sparse data: keep nameservers and ICANN/RDAP lookup URL in the report.
- Cloudflare detected: real hosting provider is usually hidden. Do not guess.
- The site blocks requests: try again with `--screenshots` because Playwright may load the page better than `requests`.

## When Responding to the User

Summarize the top findings first:

- Registrar and abuse contact
- CDN/proxy
- Platform
- Hosting visibility
- Recommended complaint order
- Output files generated

Then mention any uncertainty explicitly.
