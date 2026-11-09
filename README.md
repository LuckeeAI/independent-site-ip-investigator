# Independent Site IP Investigator Skill

OpenClaw / Hermes-compatible AgentSkills folder for investigating infringing independent ecommerce sites.

Install by copying this folder into one of:

- OpenClaw shared skills: `~/.openclaw/skills/independent-site-ip-investigator`
- OpenClaw workspace skills: `<workspace>/skills/independent-site-ip-investigator`
- Hermes skills: `~/.hermes/skills/independent-site-ip-investigator`

Then install dependencies:

```bash
cd independent-site-ip-investigator
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium  # optional, for screenshots
```

Optional LLM report generation:

```bash
export OPENAI_API_KEY="your_api_key"
export OPENAI_MODEL="gpt-5.5"
```

Run example:

```bash
python scripts/site_ip_investigator.py \
  --url "https://example-store.com/products/abc" \
  --brand "ABC Brand" \
  --company "ABC LLC" \
  --amazon-url "https://www.amazon.com/dp/B0XXXXXXX" \
  --official-url "https://abc.com/products/abc" \
  --infringement "copyright+trademark" \
  --affects-buybox yes \
  --screenshots \
  --pdf
```
