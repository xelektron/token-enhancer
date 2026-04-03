<!-- mcp-name: io.github.xelektron/token-enhancer -->
# Token Enhancer

A local proxy that strips web pages down to clean text before they enter your AI agent's context window.

**One fetch of Yahoo Finance: 704,760 tokens → 2,625 tokens. 99.6% reduction.**

No API key. No LLM. No GPU. Just Python.

## The Problem

AI agents waste most of their token budget loading raw HTML pages into context. A single Yahoo Finance page is 704K tokens of navigation bars, ads, scripts, and junk. Your agent pays for all of it before any reasoning happens.

## The Solution

Token Enhancer sits between your agent and the web. It fetches the page, strips the noise, caches the result, and returns only clean data.

| Source | Raw Tokens | After Proxy | Reduction |
|--------|-----------|-------------|-----------|
| Yahoo Finance (AAPL) | 704,760 | 2,625 | **99.6%** |
| Wikipedia article | 154,440 | 19,479 | **87.4%** |
| Hacker News | 8,662 | 859 | **90.1%** |
| GitHub repo page | 171,234 | 6,976 | **95.9%** |

## Install

```bash
pip install xelektron-token-enhancer
```

## Quick Start (from source)
```
git clone https://github.com/xelektron/token-enhancer.git
cd token-enhancer
chmod +x install.sh
./install.sh
source .venv/bin/activate
python3 test_all.py --live
```

## Usage

### As a standalone proxy
```
source .venv/bin/activate
python3 proxy.py
```

Then in another terminal:
```
curl -s http://localhost:8080/fetch \
  -H "content-type: application/json" \
  -d '{"url": "https://finance.yahoo.com/quote/AAPL/"}' \
  | python3 -m json.tool
```

### As an MCP Server (Claude Desktop, Cursor, OpenClaw)

This is the plug and play option. Your AI agent discovers the tools automatically and uses them on its own.

```bash
pip install xelektron-token-enhancer
```

**Claude Desktop:** Add to your config file

Mac: `~/Library/Application Support/Claude/claude_desktop_config.json`

Windows: `%APPDATA%\Claude\claude_desktop_config.json`
```json
{
  "mcpServers": {
    "token-enhancer": {
      "command": "python3",
      "args": ["-m", "mcp_server"],
      "env": {
        "REQUESTS_CA_BUNDLE": "/etc/ssl/certs/ca-certificates.crt"
      }
    }
  }
}
```

> On Linux hosts where SSL verification fails, the `env` block above overrides the default CA bundle. Remove it on macOS/Windows.

**Cursor:** Add to `.cursor/mcp.json` in your project:
```json
{
  "mcpServers": {
    "token-enhancer": {
      "command": "python3",
      "args": ["-m", "mcp_server"]
    }
  }
}
```

Once connected, your agent gets three tools:

`fetch_clean` fetches any URL and returns clean text (86 to 99% smaller)

`fetch_clean_batch` fetches multiple URLs at once

`refine_prompt` optional prompt cleanup, shows both versions so you decide

### As a LangChain Tool
```python
from langchain.tools import tool
import requests

@tool
def fetch_clean(url: str) -> str:
    """Fetch a URL and return clean text with HTML noise removed."""
    r = requests.post("http://localhost:8080/fetch", json={"url": url})
    return r.json()["content"]
```

Add `fetch_clean` to your agent's tool list. Start `python3 proxy.py` first.

## Features

**Data Proxy (Layer 2)**
Fetches any URL, strips HTML/JSON noise, returns clean text. Caches results so repeat fetches are instant. Handles HTML, JSON, and plain text.

**Prompt Refiner (Layer 1, opt in)**
Strips filler words and hedging while protecting tickers, dates, money values, negations, and conversation references. You see both versions and choose.

**MCP Server**
Plug into Claude Desktop, Cursor, OpenClaw, or any MCP client. Agent discovers the tools and uses them automatically.

## API Endpoints (proxy mode)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/fetch` | POST | Fetch URL, strip noise, return clean data |
| `/fetch/batch` | POST | Fetch multiple URLs at once |
| `/refine` | POST | Opt in prompt refinement |
| `/stats` | GET | Session statistics |

## Run Tests
```
python3 test_all.py           # Layer 1 only (offline)
python3 test_all.py --live    # Layer 1 + Layer 2 (needs internet)
```

## Roadmap

- [x] Layer 1: Prompt refiner
- [x] Layer 2: Data proxy with caching
- [x] MCP server integration
- [x] LangChain tool example
- [ ] Browser fallback (Playwright) for bot blocked sites
- [ ] Authenticated session management
- [ ] Layer 3: Output/history compression
- [ ] CLI tool
- [ ] Dashboard UI

## Requirements

Python 3.10+. No API keys. No GPU.

## License

MIT
