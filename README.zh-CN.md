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

运行调查前，请将下面的占位网址、品牌、公司和 ASIN 替换为你的实际信息。

```bash
git clone https://github.com/LuckeeAI/independent-site-ip-investigator.git
cd independent-site-ip-investigator
pip install -r requirements.txt

python scripts/site_ip_investigator.py \
  --url "https://copycat-store.example.com/products/your-product" \
  --brand "Your Brand" \
  --company "Your Company LLC" \
  --amazon-url "https://www.amazon.com/dp/B0XXXXXXXX" \
  --official-url "https://brand.example.com/products/your-product" \
  --lang zh
```

报告保存在 `reports/<hostname>_<timestamp>/report.md`，目录名使用完整主机名，并将点和冒号替换为下划线。加 `--screenshots` 会截取整页（需先运行一次 `python -m playwright install chromium`），加 `--pdf` 会生成 PDF。PDF 用的是 WeasyPrint，需要先装系统库：macOS 运行 `brew install pango`，Ubuntu/Debian 运行 `apt install libpango-1.0-0 libpangoft2-1.0-0`。任何 PDF 失败都会向 stderr 输出可读警告，并保留 Markdown 报告；缺少 Python 包时提示 `pip install markdown2 weasyprint`，缺少系统库时提示上述平台安装步骤。投诉信模板始终是英文，因为要提交给海外平台。

中文 PDF 还需要覆盖中文字符的字体。若出现方块或缺字，请安装中文字体后重新生成。

### 批量调查

把网址放进 CSV（参考 [`examples/sites.csv`](examples/sites.csv)，使用前需替换其中的占位值）：

```bash
python scripts/site_ip_investigator.py --csv sites.csv --lang zh --screenshots
```

每行生成一个调查文件夹，并在 `reports/batch_<timestamp>/` 下汇总成 `batch_summary.csv` 和 `batch_summary.md`。非法输入及无法确认存在的主机会保留 `investigation.json` 错误记录，不生成投诉报告。单行失败不会中断后续行。PDF 错误会加入 `error` 列，同时保留已有 HTTP 错误，并计入出错行数；Markdown 报告仍可使用。只要整批处理完成，退出码就是 `0`，即使部分或全部行失败，因此仍须检查 `error` 列。

### 作为 agent skill 使用

把整个文件夹复制到 agent 的 skills 目录，例如 `~/.claude/skills/independent-site-ip-investigator`、`~/.openclaw/skills/` 或 `~/.hermes/skills/`。然后直接说：*"这家店在用我们的图：https://… 帮我查一下该去哪投诉。"*

## 示例：挂了 Cloudflare 的 Shopify 店

以下是示意输出，域名和联系方式均为占位值：

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

这个示例中，网站前面挂着 Cloudflare，DNS 指向 Shopify，因此工具将 Shopify 识别为主机，并把它的举报表单排在投诉顺序第一位。识别出 Shopify 平台后，CDN 列表会去掉重复的 Shopify CDN。平台识别结果本身不构成侵权认定。

### 开在平台二级域名上的店

很多仿品店根本不买域名，直接用 `your-brand-deals.myshopify.com`、`xxx.wixsite.com` 这样的地址。工具能识别这种情况，并提示你直接向平台投诉。如果去找 `myshopify.com` 的注册商，投诉只会到 Shopify 自己的域名注册商那里。

非法网址的退出码为 `2`。只有 DNS 没有 A/AAAA/CNAME 记录、RDAP 没有提供注册证据且未收到 HTTP 响应时，工具才会判定无法确认该主机存在：保留 `investigation.json`，跳过投诉报告，单站模式退出码为 `3`。请检查网址和网络后重试；查询失败不代表域名未注册。只要 DNS 或 RDAP 提供了证据，或收到任何 HTTP 响应（包括 403/404/503），就会继续生成报告；页面未能成功加载时，报告会提示你在投诉前自行截图取证。

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

默认使用 `--llm none`，即使设置了 API 密钥也不会调用模型。如果想让模型基于同样的证据写一份更完整的叙述：

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
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
```

测试全部离线运行，DNS、RDAP 和 HTTP 均为模拟数据。

## 许可

[MIT](LICENSE)。由 [Luckee](https://luckee.ai/?utm_source=github&utm_medium=readme&utm_campaign=independent-site-ip-investigator&utm_content=credits-zh) 开发和维护。
