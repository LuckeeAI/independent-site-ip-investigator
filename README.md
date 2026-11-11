# Independent Site IP Investigator

Found an independent store using your product photos or brand name? Give this tool the URL. It finds out who registers the domain, which platform and CDN serve it, where to send the takedown, and drafts the DMCA, trademark and Amazon Buy Box notices for you.

**English** · [简体中文](README.zh-CN.md)

![License: MIT](https://img.shields.io/badge/license-MIT-15803d) ![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-1f2937) ![Agent skill](https://img.shields.io/badge/agent-skill-0e7490)

Works as a plain Python CLI or as a skill for Claude Code, OpenClaw, Hermes and other agents that read `SKILL.md`. Shared by [Luckee](https://luckee.ai/?utm_source=github&utm_medium=readme&utm_campaign=independent-site-ip-investigator&utm_content=intro).

## The problem

A copycat Shopify store lifts your Amazon photos and sells a lookalike for less. Reporting it is harder than it should be:

- WHOIS shows a privacy service, so you don't know who runs the site
- Cloudflare sits in front, so you can't see the real host
- You don't know whether to complain to the registrar, the CDN, the store platform or Google
- If Amazon matches your listing to that cheaper page, you can lose the Featured Offer (Buy Box), and your Sponsored Products ads stop serving with it

This tool does the lookup work and tells you which channel is most likely to act.

## What it finds

For any store URL or domain:

| | How |
|---|---|
| **Registrar** + abuse email and phone | RDAP (the replacement for WHOIS) |
| **Store platform**: Shopify, WooCommerce, Wix, Squarespace, BigCommerce, Magento, Shopline, Shoplazza and more | Page source fingerprints, DNS records, known platform IP ranges |
| **CDN / proxy**: Cloudflare, Akamai, Fastly, CloudFront, Vercel and more | Response headers, DNS, Cloudflare's published IP ranges |
| **Hosting provider** and ASN | IP RDAP, unless hidden behind a proxy |
| **Possible payment providers**: PayPal, Stripe, Shop Pay, Klarna and more | Scripts on the page (checkout may load others) |
| **Full-page screenshot** | Playwright (optional) |

Then it writes:

- A report in English or Chinese with the evidence and a **complaint order**: which channel to try first and its official reporting link
- A **DMCA notice** for copied images, a **trademark complaint** for brand misuse, and an **Amazon Seller Support case** asking to drop the external price match and restore your Featured Offer
- A JSON file with all the raw data, and an optional PDF

It never submits anything. You review the drafts and file them yourself.

## Quick start

Replace the placeholder URLs, brand, company and ASIN below with your own inputs before running the investigation.

```bash
git clone https://github.com/LuckeeAI/independent-site-ip-investigator.git
cd independent-site-ip-investigator
pip install -r requirements.txt

python scripts/site_ip_investigator.py \
  --url "https://copycat-store.example.com/products/your-product" \
  --brand "Your Brand" \
  --company "Your Company LLC" \
  --amazon-url "https://www.amazon.com/dp/B0XXXXXXXX" \
  --official-url "https://brand.example.com/products/your-product"
```

The report lands in `reports/<hostname>_<timestamp>/report.md`, using the full hostname with dots and colons replaced by underscores. Add `--lang zh` for a Chinese report, `--screenshots` for a full-page capture (run `python -m playwright install chromium` once), and `--pdf` for a PDF. PDF output uses WeasyPrint, which needs system libraries: `brew install pango` on macOS, `apt install libpango-1.0-0 libpangoft2-1.0-0` on Ubuntu/Debian. Every PDF failure prints a readable warning to stderr and preserves the Markdown report; missing Python packages prompt `pip install markdown2 weasyprint`, and missing system libraries prompt the platform-specific steps above.

Chinese PDF output also requires a font with Chinese glyph coverage. If characters are missing, install a suitable font and regenerate the PDF.

### Many sites at once

Put the URLs in a CSV (see [`examples/sites.csv`](examples/sites.csv), whose placeholder values must be replaced):

```bash
python scripts/site_ip_investigator.py --csv sites.csv --screenshots
```

You get one investigation folder per row plus `batch_summary.csv` and `batch_summary.md` under `reports/batch_<timestamp>/`. Invalid inputs and hosts that cannot be confirmed retain an `investigation.json` error record without a complaint report. Row failures do not stop later rows. PDF errors are added to the `error` column alongside any HTTP error and count toward rows with errors; Markdown reports remain available. A completed batch exits with status `0` even when some or all rows fail, so always inspect the `error` column.

### As an agent skill

Copy the folder into your agent's skills directory, for example `~/.claude/skills/independent-site-ip-investigator`, `~/.openclaw/skills/` or `~/.hermes/skills/`. Then ask in plain language: *"This store is using our photos: https://… Find out where to report it."*

## Example: a Shopify store behind Cloudflare

Illustrative output, with placeholder domain and contact details:

```json
{
  "domain": "example.com",
  "hostname": "store.example.com",
  "registrable_domain": "example.com",
  "registrar": "Example Registrar",
  "abuse_email": "abuse@registrar.example",
  "cdn": ["Cloudflare"],
  "platform": ["Shopify"],
  "hosting_status": "platform_hosted"
}
```

In this example, Cloudflare is in front and DNS points to Shopify, so the tool reports Shopify as the host and puts its report form first. When Shopify is identified as the platform, the duplicate Shopify CDN finding is omitted. Platform detection alone does not establish infringement.

### Stores on a platform's own domain

Many copycat stores never buy a domain and run on addresses like `your-brand-deals.myshopify.com` or `xxx.wixsite.com`. The tool recognises these and tells you to report the store to the platform directly. Complaining to the registrar of `myshopify.com` would only reach Shopify's own domain registrar.

Invalid URLs exit with status `2`. If DNS provides no A/AAAA/CNAME records, RDAP provides no registration evidence, and no HTTP response is received, the tool cannot confirm the host: it saves `investigation.json`, skips the complaint report and exits with status `3` in single-site mode. Check the URL and network, then retry; lookup failures do not prove the domain is unregistered. DNS or RDAP evidence, or any HTTP response (including 403/404/503), is enough to continue. If the page could not be loaded successfully, the report warns you to capture your own screenshot before filing.

## Which complaint goes first

| Order | Channel | When it works best |
|---|---|---|
| 1 | Store platform (Shopify, Wix, BigCommerce…) | Almost always. Platforms remove listings and can close stores. |
| 2 | Cloudflare / CDN | In parallel. Cloudflare forwards the report to the host and the site owner. |
| 3 | Hosting provider | When the host is visible and not behind a proxy |
| 4 | Domain registrar | Fake stores, impersonation, repeat offenders |
| 5 | Google search removal | If the page stays live, to cut its traffic |
| 6 | Amazon Seller Support | If the page cost you the Buy Box. Attach the takedown confirmations from 1–5. |

## What it won't do

- **Guess the real host behind Cloudflare.** If it's hidden, the report says so.
- **Confirm payment providers.** Payment scripts often load only at checkout, so these are marked "possible".
- **Make up contacts.** If RDAP has no abuse email, the field is empty and the report tells you where to look manually.
- **Decide whether something is infringing.** Make sure you own the rights, or are authorized by the owner, before filing. A DMCA notice is a sworn statement.

## Optional: AI-written report

The default report uses `--llm none` and makes no model calls, even when API keys are set. To have a model write a fuller narrative from the same evidence:

```bash
pip install anthropic          # or: pip install openai
export ANTHROPIC_API_KEY=...   # or OPENAI_API_KEY
export ANTHROPIC_MODEL=...     # or OPENAI_MODEL, the model ID you want
python scripts/site_ip_investigator.py --url ... --llm anthropic
```

If the call fails, you still get the standard report.

## Options

| Flag | What it does |
|---|---|
| `--url` / `--csv` | One site, or a CSV of sites |
| `--brand`, `--company`, `--amazon-url`, `--official-url` | Filled into the notices |
| `--infringement` | `copyright`, `trademark` or `copyright+trademark` (default) |
| `--affects-buybox` | `yes` (default) or `no` |
| `--lang` | `en` (default) or `zh` |
| `--screenshots`, `--pdf` | Full-page screenshot, PDF report |
| `--llm` | `none` (default), `anthropic` or `openai` |
| `--output-dir` | Where reports go (default `reports/`) |

## Pairs with

[**amazon-image-theft-monitor**](https://github.com/LuckeeAI/amazon-image-theft-monitor) finds the Temu, eBay, Walmart and independent-store listings that copied your photos. This tool takes each independent store it finds and works out where to report it.

## After the Buy Box comes back

While you don't have the Featured Offer, your Sponsored Products ads don't serve. Once it comes back, check your bids, budgets and search terms before you scale spend again.

[Luckee](https://luckee.ai/features/amazon-ads?utm_source=github&utm_medium=readme&utm_campaign=independent-site-ip-investigator&utm_content=after-buybox) is your AI Amazon PPC expert. It reads your campaign data, explains what changed, and proposes bid, budget and keyword changes. Nothing runs until you approve it. [Try free for 7 days →](https://luckee.ai/features/amazon-ads?utm_source=github&utm_medium=readme&utm_campaign=independent-site-ip-investigator&utm_content=after-buybox-cta)

## Development

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
```

Tests run offline with mocked DNS, RDAP and HTTP.

## License

[MIT](LICENSE). Built and maintained by [Luckee](https://luckee.ai/?utm_source=github&utm_medium=readme&utm_campaign=independent-site-ip-investigator&utm_content=credits).
