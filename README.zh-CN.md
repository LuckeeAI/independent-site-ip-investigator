# 独立站侵权调查工具

发现有独立站盗用你的产品图或品牌名？把网址交给这个工具。它会查出域名注册商、网站用的建站平台和 CDN、该向谁投诉，并替你起草 DMCA 投诉、商标投诉和亚马逊 Buy Box 申诉。

[English](README.md) · **简体中文**

![License: MIT](https://img.shields.io/badge/license-MIT-15803d) ![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-1f2937) ![Agent skill](https://img.shields.io/badge/agent-skill-0e7490)

既可以当 Python 命令行工具用，也可以作为 Claude Code、OpenClaw、Hermes 等读取 `SKILL.md` 的 AI agent 的 skill 使用。由 [Luckee](https://luckee.ai/?utm_source=github&utm_medium=readme&utm_campaign=independent-site-ip-investigator&utm_content=intro-zh) 整理开源。

## 遇到的问题

一家仿品 Shopify 店盗用了你在亚马逊上的产品图，用更低的价格卖相似的东西。想投诉它，比想象中麻烦：

- WHOIS 信息被隐私保护遮住了，不知道网站是谁在运营
- 网站前面挂着 Cloudflare，看不到真实的主机
- 不知道该找注册商、CDN、建站平台还是 Google
- 如果亚马逊把你的 listing 和这个更便宜的页面做了价格匹配，你可能会丢掉 Featured Offer（Buy Box），你的 Sponsored Products 广告也会跟着停止投放

这个工具帮你把这些信息查清楚，并告诉你先找哪个渠道最可能有效。

## 能查到什么

输入任意独立站网址或域名：

| | 方法 |
|---|---|
| **注册商**及投诉邮箱、电话 | RDAP（WHOIS 的替代协议） |
| **建站平台**：Shopify、WooCommerce、Wix、Squarespace、BigCommerce、Magento、Shopline、Shoplazza 等 | 网页源码特征、DNS 记录、平台已知 IP 段 |
| **CDN / 代理**：Cloudflare、Akamai、Fastly、CloudFront、Vercel 等 | 响应头、DNS、Cloudflare 公布的 IP 段 |
| **主机服务商**及 ASN | IP 的 RDAP 信息（被代理隐藏时除外） |
| **可能的支付服务商**：PayPal、Stripe、Shop Pay、Klarna 等 | 页面中加载的脚本（结账页可能还有别的） |
| **整页截图** | Playwright（可选） |

然后生成：

- 一份中文或英文调查报告，包含证据和**投诉顺序**：先找哪个渠道，以及它的官方投诉入口
- 盗图用的 **DMCA 投诉信**、品牌被冒用时的**商标投诉信**，以及一份**亚马逊卖家支持 case**，请求取消站外价格匹配、恢复 Featured Offer
- 一个包含全部原始数据的 JSON 文件，PDF 可选

它不会替你提交任何东西。草稿由你审核，再自己去提交。

## 快速开始

```bash
git clone https://github.com/LuckeeAI/independent-site-ip-investigator.git
cd independent-site-ip-investigator
pip install -r requirements.txt

python scripts/site_ip_investigator.py \
  --url "https://copycat-store.example.com/products/your-product" \
  --brand "Your Brand" \
  --company "Your Company LLC" \
  --amazon-url "https://www.amazon.com/dp/B0XXXXXXXX" \
  --official-url "https://yourbrand.com/products/your-product" \
  --lang zh
```

报告保存在 `reports/<域名>_<时间>/report.md`。加 `--screenshots` 会截取整页（需先运行一次 `python -m playwright install chromium`），加 `--pdf` 会生成 PDF。投诉信模板始终是英文，因为要提交给海外平台。

### 批量调查

把网址放进 CSV（参考 [`examples/sites.csv`](examples/sites.csv)）：

```bash
python scripts/site_ip_investigator.py --csv sites.csv --lang zh --screenshots
```

每个网站生成一个报告文件夹，另外汇总成 `batch_summary.csv` 和 `batch_summary.md`。某个网站打不开不会中断整批任务，错误会记在它那一行。

### 作为 agent skill 使用

把整个文件夹复制到 agent 的 skills 目录，例如 `~/.claude/skills/independent-site-ip-investigator`、`~/.openclaw/skills/` 或 `~/.hermes/skills/`。然后直接说：*"这家店在用我们的图：https://… 帮我查一下该去哪投诉。"*

## 示例：挂了 Cloudflare 的 Shopify 店

```json
{
  "domain": "brand-store.com",
  "registrar": "MarkMonitor Inc.",
  "abuse_email": "abusecomplaints@markmonitor.com",
  "cdn": ["Cloudflare", "Shopify CDN"],
  "platform": ["Shopify"],
  "hosting_status": "platform_hosted"
}
```

这是对一个正规品牌自营 Shopify 店的真实查询结果，域名已隐去。虽然前面挂着 Cloudflare，但 DNS 指向 Shopify，所以工具判断主机就是 Shopify，并把 Shopify 的举报表单排在投诉顺序第一位，因为平台可以直接下架店铺的商品页。

## 先投诉哪里

| 顺序 | 渠道 | 适用情况 |
|---|---|---|
| 1 | 建站平台（Shopify、Wix、BigCommerce 等） | 几乎所有情况。平台可以下架商品，也可以关店。 |
| 2 | Cloudflare / CDN | 同时提交。Cloudflare 会把投诉转给主机商和网站所有者。 |
| 3 | 主机服务商 | 主机可见、没有被代理隐藏时 |
| 4 | 域名注册商 | 仿冒店、冒充品牌、屡次侵权 |
| 5 | Google 搜索移除 | 页面一直不下线时，减少它的流量 |
| 6 | 亚马逊卖家支持 | 这个页面让你丢了 Buy Box 时。附上 1–5 步拿到的下架确认。 |

## 它不会做的事

- **不猜 Cloudflare 后面的真实主机。** 被隐藏了，报告里就如实写明。
- **不确认支付服务商。** 支付脚本常常只在结账页加载，所以只标为"可能"。
- **不编造联系方式。** RDAP 里没有投诉邮箱，就留空，并告诉你去哪里人工查。
- **不替你判断是否侵权。** 提交前请确认你是权利人或已获授权。DMCA 投诉是一份宣誓声明。

## 可选：让 AI 写报告

默认报告完全根据数据生成，不调用任何 AI。如果想让模型基于同样的证据写一份更完整的叙述：

```bash
pip install anthropic          # 或 pip install openai
export ANTHROPIC_API_KEY=...   # 或 OPENAI_API_KEY
export ANTHROPIC_MODEL=...     # 或 OPENAI_MODEL，填你要用的模型 ID
python scripts/site_ip_investigator.py --url ... --llm anthropic --lang zh
```

调用失败时，仍然会生成标准报告。

## 参数

| 参数 | 作用 |
|---|---|
| `--url` / `--csv` | 单个网站，或一个网站列表 CSV |
| `--brand`、`--company`、`--amazon-url`、`--official-url` | 填入投诉信 |
| `--infringement` | `copyright`、`trademark` 或 `copyright+trademark`（默认） |
| `--affects-buybox` | `yes`（默认）或 `no` |
| `--lang` | `en`（默认）或 `zh` |
| `--screenshots`、`--pdf` | 整页截图、PDF 报告 |
| `--llm` | `none`（默认）、`anthropic` 或 `openai` |
| `--output-dir` | 报告保存位置（默认 `reports/`） |

## 搭配使用

[**amazon-image-theft-monitor**](https://github.com/LuckeeAI/amazon-image-theft-monitor) 负责找出盗用你产品图的 Temu、eBay、Walmart 和独立站链接。它找到的每个独立站，都可以交给这个工具查清该去哪投诉。

## Buy Box 恢复之后

没有 Featured Offer 的这段时间，你的 Sponsored Products 广告不会展示。恢复以后，先检查出价、预算和搜索词，再重新加大投放。

[Luckee](https://luckee.ai/features/amazon-ads?utm_source=github&utm_medium=readme&utm_campaign=independent-site-ip-investigator&utm_content=after-buybox-zh) 是你的 AI 亚马逊广告专家。它读取你的广告数据，解释发生了什么变化，并给出出价、预算和关键词的调整建议。每一项改动都要经你确认才会执行。[免费试用 7 天 →](https://luckee.ai/features/amazon-ads?utm_source=github&utm_medium=readme&utm_campaign=independent-site-ip-investigator&utm_content=after-buybox-cta-zh)

## 开发

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

测试全部离线运行，DNS、RDAP 和 HTTP 均为模拟数据。

## 许可

[MIT](LICENSE)。由 [Luckee](https://luckee.ai/?utm_source=github&utm_medium=readme&utm_campaign=independent-site-ip-investigator&utm_content=credits-zh) 开发和维护。
