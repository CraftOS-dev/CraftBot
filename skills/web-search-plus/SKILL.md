---
name: web-search-plus
version: 2.8.1
description: Unified search skill with Intelligent Auto-Routing. Uses multi-signal analysis to automatically select between Serper (Google), Tavily (Research), Exa (Neural), Perplexity (AI Answers), You.com (RAG/Real-time), and SearXNG (Privacy/Self-hosted) with confidence scoring.
tags: [search, web-search, serper, tavily, exa, perplexity, you, searxng, google, research, semantic-search, auto-routing, multi-provider, shopping, rag, free-tier, privacy, self-hosted, kilo]
metadata: {"openclaw":{"requires":{"bins":["python3","bash"],"env":{"SERPER_API_KEY":"optional","TAVILY_API_KEY":"optional","EXA_API_KEY":"optional","YOU_API_KEY":"optional","SEARXNG_INSTANCE_URL":"optional","KILOCODE_API_KEY":"optional — required for Perplexity provider (via Kilo Gateway)"},"note":"Only ONE provider key needed. All are optional."}}}
---

# Web Search Plus

**Stop choosing search providers. Let the skill do it for you.**

This skill connects you to 6 search providers (Serper, Tavily, Exa, Perplexity, You.com, SearXNG) and automatically picks the best one for each query. Shopping question? → Google results. Research question? → Deep research engine. Need a direct answer? → AI-synthesized with citations. Want privacy? → Self-hosted option.

---

## ✨ What Makes This Different?

- **Just search** — No need to think about which provider to use
- **Smart routing** — Analyzes your query and picks the best provider automatically
- **6 providers, 1 interface** — Google results, research engines, neural search, AI answers with citations, RAG-optimized, and privacy-first all in one
- **Works with just 1 key** — Start with any single provider, add more later
- **Free options available** — SearXNG is completely free (self-hosted)

---

## 🚀 Quick Start

```bash
# Interactive setup (recommended for first run)
python3 scripts/setup.py

# Or manual: copy config and add your keys
cp config.example.json config.json
```

The wizard explains each provider, collects API keys, and configures defaults.

---

## 🔑 API Keys

You only need **ONE** key to get started. Add more providers later for better coverage.

| Provider | Free Tier | Best For | Sign Up |
|----------|-----------|----------|---------|
| **Serper** | 2,500/mo | Shopping, prices, local, news | [serper.dev](https://serper.dev) |
| **Tavily** | 1,000/mo | Research, explanations, academic | [tavily.com](https://tavily.com) |
| **Exa** | 1,000/mo | "Similar to X", startups, papers | [exa.ai](https://exa.ai) |
| **Perplexity** | Via Kilo | Direct answers with citations | [kilo.ai](https://kilo.ai) |
| **You.com** | Limited | Real-time info, AI/RAG context | [api.you.com](https://api.you.com) |
| **SearXNG** | **FREE** ✅ | Privacy, multi-source, $0 cost | Self-hosted |

**Setting your keys:**

```bash
# Option A: .env file (recommended)
export SERPER_API_KEY="your-key"
export TAVILY_API_KEY="your-key"

# Option B: config.json
{ "serper": { "api_key": "your-key" } }
```

---

## 🎯 When to Use Which Provider

| I want to... | Provider | Example Query |
|--------------|----------|---------------|
| Find product prices | **Serper** | "iPhone 16 Pro Max price" |
| Find restaurants/stores nearby | **Serper** | "best pizza near me" |
| Understand how something works | **Tavily** | "how does HTTPS encryption work" |
| Do deep research | **Tavily** | "climate change research 2024" |
| Find companies like X | **Exa** | "startups similar to Notion" |
| Find research papers | **Exa** | "transformer architecture papers" |
| Get a direct answer with sources | **Perplexity** | "events in Berlin this weekend" |
| Know the current status of something | **Perplexity** | "what is the status of Ethereum upgrades" |
| Get real-time info | **You.com** | "latest AI regulation news" |
| Search without being tracked | **SearXNG** | anything, privately |

**Pro tip:** Just search normally! Auto-routing handles most queries correctly. Override with `-p provider` when needed.

---

## 🧠 How Auto-Routing Works

The skill looks at your query and picks the best provider:

```bash
"iPhone 16 price"              → Serper (shopping keywords)
"how does quantum computing work" → Tavily (research question)
"companies like stripe.com"    → Exa (URL detected, similarity)
"events in Graz this weekend"  → Perplexity (local + direct answer)
"latest news on AI"            → You.com (real-time intent)
"search privately"             → SearXNG (privacy keywords)
```

**What if it picks wrong?** Override it: `python3 scripts/search.py -p tavily -q "your query"`

**Debug routing:** `python3 scripts/search.py --explain-routing -q "your query"`

---

## 📖 Usage Examples

### Let Auto-Routing Choose (Recommended)

```bash
python3 scripts/search.py -q "Tesla Model 3 price"
python3 scripts/search.py -q "explain machine learning"
python3 scripts/search.py -q "startups like Figma"
```

### Force a Specific Provider

```bash
python3 scripts/search.py -p serper -q "weather Berlin"
python3 scripts/search.py -p tavily -q "quantum computing" --depth advanced
python3 scripts/search.py -p exa --similar-url "https://stripe.com" --category company
python3 scripts/search.py -p you -q "breaking tech news" --include-news
python3 scripts/search.py -p searxng -q "linux distros" --engines "google,bing"
```

---

## ⚙ Configuration

```json
{
  "auto_routing": {
    "enabled": true,
    "fallback_provider": "serper",
    "confidence_threshold": 0.3,
    "disabled_providers": []
  },
  "serper": {"country": "us", "language": "en"},
  "tavily": {"depth": "advanced"},
  "exa": {"type": "neural"},
  "you": {"country": "US", "include_news": true},
  "searxng": {"instance_url": "https://your-instance.example.com"}
}
```

---

## 📊 Provider Comparison

| Feature | Serper | Tavily | Exa | Perplexity | You.com | SearXNG |
|---------|:------:|:------:|:---:|:----------:|:-------:|:-------:|
| Speed | ⚡⚡⚡ | ⚡⚡ | ⚡⚡ | ⚡⚡ | ⚡⚡⚡ | ⚡⚡ |
| Direct Answers | ✗ | ✗ | ✗ | ✓✓ | ✗ | ✗ |
| Citations | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ |
| Factual Accuracy | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |
| Semantic Understanding | ⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐ |
| Full Page Content | ✗ | ✓ | ✓ | ✓ | ✓ | ✗ |
| Shopping/Local | ✓ | ✗ | ✗ | ✗ | ✗ | ✓ |
| Find Similar Pages | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ |
| RAG-Optimized | ✗ | ✓ | ✗ | ✗ | ✓✓ | ✗ |
| Privacy-First | ✗ | ✗ | ✗ | ✗ | ✗ | ✓✓ |
| API Cost | $$ | $$ | $$ | Via Kilo | $ | **FREE** |

---

## ❓ Common Questions

### Do I need API keys for all providers?
**No.** You only need keys for providers you want to use. Start with one (Serper recommended), add more later.

### Which provider should I start with?
**Serper** — fastest, cheapest, largest free tier (2,500 queries/month), and handles most queries well.

### What if I run out of free queries?
The skill automatically falls back to your other configured providers. Or switch to SearXNG (unlimited, self-hosted).

### How much does this cost?
- **Free tiers:** 2,500 (Serper) + 1,000 (Tavily) + 1,000 (Exa) = 4,500+ free searches/month
- **SearXNG:** Completely free (just ~$5/mo if you self-host on a VPS)
- **Paid plans:** Start around $10-50/month depending on provider

### Is SearXNG really private?
**Yes, if self-hosted.** You control the server, no tracking, no profiling. Public instances depend on the operator's policy.

### How do I set up SearXNG?
```bash
# Docker (5 minutes)
docker run -d -p 8080:8080 searxng/searxng
```
Then enable JSON API in `settings.yml`. See [docs.searxng.org](https://docs.searxng.org/admin/installation.html).

### Why did it route my query to the "wrong" provider?
Sometimes queries are ambiguous. Use `--explain-routing` to see why, then override with `-p provider` if needed.

---

## 🔄 Automatic Fallback

If one provider fails (rate limit, timeout, error), the skill automatically tries the next provider. You'll see `routing.fallback_used: true` in the response when this happens.

---

## 📤 Output Format

```json
{
  "provider": "serper",
  "query": "iPhone 16 price",
  "results": [{"title": "...", "url": "...", "snippet": "...", "score": 0.95}],
  "routing": {
    "auto_routed": true,
    "provider": "serper",
    "confidence": 0.78,
    "confidence_level": "high"
  }
}
```

---

## ⚠ Important Note

**Tavily, Serper, and Exa are NOT core OpenClaw providers.**

❌ Don't modify `~/.openclaw/openclaw.json` for these  
✅ Use this skill's scripts — keys auto-load from `.env`

---

## 🔒 Security

**SearXNG SSRF Protection:** The SearXNG instance URL is validated with defense-in-depth:
- Enforces `http`/`https` schemes only
- Blocks cloud metadata endpoints (169.254.169.254, metadata.google.internal)
- Resolves hostnames and blocks private/internal IPs (loopback, RFC1918, link-local, reserved)
- Operators who intentionally self-host on private networks can set `SEARXNG_ALLOW_PRIVATE=1`

## 📚 More Documentation

- **[FAQ.md](FAQ.md)** — Detailed answers to more questions
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** — Fix common errors
- **[README.md](README.md)** — Full technical reference

---

## 🔗 Quick Links

- [Serper](https://serper.dev) — Google Search API
- [Tavily](https://tavily.com) — AI Research Search
- [Exa](https://exa.ai) — Neural Search
- [Perplexity](https://www.perplexity.ai) — AI-Synthesized Answers (via [Kilo Gateway](https://kilo.ai))
- [You.com](https://api.you.com) — RAG/Real-time Search
- [SearXNG](https://docs.searxng.org) — Privacy-First Meta-Search
