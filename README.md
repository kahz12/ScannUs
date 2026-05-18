<div align="center">

```
 ____                        _   _
/ ___|  ___ __ _ _ __  _ __ | | | |___
\___ \ / __/ _` | '_ \| '_ \| | | / __|
 ___) | (_| (_| | | | | | | | |_| \__ \
|____/ \___\__,_|_| |_|_| |_|\___/|___/
```

**Advanced OSINT & Web Intelligence Framework**

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Active-brightgreen?style=flat-square)]()
[![Platforms](https://img.shields.io/badge/Platforms-Linux%20%7C%20Windows%20%7C%20Termux-orange?style=flat-square)]()

</div>

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Features](#features)
4. [Installation](#installation)
5. [Configuration](#configuration)
6. [Usage](#usage)
7. [Project Structure](#project-structure)
8. [Cache & Storage](#cache--storage)
9. [Disclaimer](#disclaimer)

---

## Overview

**ScannUs** is a modular OSINT framework that unifies multi-engine search, AI-assisted planning, breach-intelligence lookups, domain reconnaissance, deep PII extraction, and evidence collection behind a single interactive terminal.

It turns a raw lead — an email, a handle, a domain — into a structured, reproducible investigation: cached, exportable, and ready to share.

### Highlights

| Capability | What you get |
|---|---|
| **Multi-engine search** | Google CSE · DuckDuckGo · Brave — persistent SQLite cache |
| **Four AI providers** | Gemini · GPT-4o · Claude Sonnet 4.6 · local Ollama — token-streamed |
| **AI Query Planner** | ReAct-style multi-step investigation plans using 22 whitelisted tools |
| **Breach intelligence** | Have I Been Pwned — accounts, domains, breaches, k-anon passwords |
| **Domain recon** | WHOIS + DNS + TLS + security headers + crt.sh subdomains + Shodan |
| **PII & secret extraction** | AWS/GitHub/Slack/Stripe keys · JWTs · BTC/ETH · IBANs · SSN/CPF/SIN |
| **Username enumeration** | Sherlock / Maigret — 400+ social sites |
| **Wayback Machine** | Snapshot fetch · PII extraction · unified-diff between dates |
| **Reverse image search** | TinEye + Bing Visual + Yandex + manual fallbacks |
| **Evidence collection** | Full-page screenshots · media downloader (yt-dlp tier) · file metadata |
| **Export** | Excel · CSV · JSON · HTML reports — clickable, styled |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                          Entry Point                                 │
│                           main.py                                    │
└────────────────────────────┬─────────────────────────────────────────┘
                             │
          ┌──────────────────▼──────────────────┐
          │              CLI Layer               │
          │  parser.py  ·  menus.py  ·  ui.py    │
          │              actions.py              │
          └──────────────────┬───────────────────┘
                             │
     ┌───────────────────────▼────────────────────────┐
     │                   Core Layer                    │
     │  config · ai_agent (4 providers + planner)      │
     │  cache (SQLite) · case_manager · state          │
     └──────┬───────────────┬──────────────────────────┘
            │               │
   ┌────────▼──────┐  ┌─────▼─────────────────────────┐
   │  Search Layer │  │       Analysis Layer          │
   │  engines/     │  │  web_analyzer · tech_scanner  │
   │  smart_search │  │  advanced_osint · domain_osint│
   │  reverse_*    │  │  hibp                         │
   │  username_enum│  │                               │
   └───────────────┘  └────────────────┬──────────────┘
                                       │
                          ┌────────────▼────────────┐
                          │       Utils Layer       │
                          │  media_downloader       │
                          │  results_parse          │
                          │  file_download          │
                          └─────────────────────────┘
```

### Design patterns

| Pattern | Location | Purpose |
|---|---|---|
| Strategy | `core/ai_agent.py` | Switchable AI backends (Gemini · OpenAI · Claude · Ollama) |
| ReAct | `IAAgent.plan` / `execute_plan` | Whitelisted tool catalog with iterative re-planning |
| Factory | `search/engines/` | Engine instantiation at runtime |
| DAO | `core/database.py` · `core/cache.py` | SQLite case storage + persistent TTL cache |
| Singleton | `core/cache.get_cache()` | Process-wide cache with WAL journal mode |
| State | `core/state.py` | Cross-module runtime state |

---

## Features

### 🔍 Search & Intelligence

- **Multi-engine search** — Google Custom Search, DuckDuckGo (HTML scraper), Brave Search. Persistent SQLite cache with per-namespace TTLs (24h for SERPs, 6h for HTTP text, 7d for WHOIS).
- **AI Query Planner** — describe a goal; the LLM produces a 3–8 step plan composed only of whitelisted tools. Each step is interactively confirmable, and the planner can re-plan from observations (ReAct).
- **AI Dork Generator** — natural language → precise Google Dork syntax.
- **Guided Search** — name · handle · email · phone → compound `AND` query.
- **Username Enumeration** — Sherlock (pure-Python, 400+ sites) or Maigret (3000+, Linux/macOS only).
- **Reverse Image Search** — TinEye API → Bing Visual API → Yandex scraping → manual-URL fallback. Multi-tier so something always returns.

### 🤖 AI Analysis (Streaming)

| Provider | Model | Cost | Use case |
|---|---|---|---|
| Google Gemini | `gemini-2.0-flash` | Free tier | Default — fast, free, capable |
| OpenAI | `gpt-4o` | Paid | Highest quality |
| Anthropic | `claude-sonnet-4-6` | Paid | Excellent for analytical reasoning |
| Ollama | `llama3` (configurable) | Free (local) | Air-gapped, privacy-preserving |

- **Token streaming** — output appears incrementally; no waiting on full completion.
- **Webpage summarisation & deep OSINT analysis** — entity extraction, relationship discovery, lead generation.
- **Long-text chunking** — 12 KB overlapping windows for content exceeding model context.
- **Entity relationship graph** — Pyvis-rendered interactive HTML graph saved to `outputs/graphs/`.

### 🔒 Breach & Leak Intelligence (HIBP)

- **Account lookup** — every breach + paste containing an email (paid HIBP key).
- **Domain breaches** — every breach affecting a domain (free).
- **Breach details** — full metadata for a single named breach (free).
- **Pwned Passwords** — k-anonymity SHA-1 lookup; plaintext **never leaves the process** — only the first 5 hex chars are sent.

### 🌐 Domain & Network OSINT

- **WHOIS** — registrar, creation/expiry, contacts, nameservers (7-day cache).
- **DNS records** — A, AAAA, MX, NS, TXT, SOA, CNAME, CAA (1-hour cache).
- **Email security** — SPF, DMARC, DKIM selector hints.
- **TLS certificate** — subject, SANs, validity window, cipher suite.
- **HTTP security headers** — HSTS, CSP, COOP, COEP, CORP scoring.
- **Subdomain enumeration** — passive via crt.sh Certificate Transparency logs.
- **Shodan host lookup** — service banners, open ports (optional, needs key).

### 🕰 Wayback Machine

- **Snapshot timeline** — CDX query for a URL's archive history.
- **Snapshot fetch** — raw archived content at a specific timestamp.
- **Snapshot PII extraction** — surface identifiers from old versions that the live site has scrubbed.
- **Snapshot diff** — unified diff of visible text between two timestamps with SHA-256 fingerprint.

### 🎯 PII & Secret Extraction

Detects and validates 25+ identifier types from any page or text:

| Category | Examples |
|---|---|
| **Cloud / API keys** | AWS (`AKIA…`), GitHub PAT, GitLab, Slack, Stripe, Google, Discord, Telegram |
| **Crypto wallets** | Bitcoin (base58check + Bech32), Ethereum (EIP-55 Keccak) |
| **National IDs** | US SSN, Argentine DNI/CUIT, Mexican RFC, Brazilian CPF (mod-11), Canadian SIN (Luhn) |
| **Financial** | IBAN, credit card (Luhn) |
| **Network** | Public IPv4/IPv6 (filtered for private/loopback/multicast), MAC addresses |
| **Tokens** | JWTs (header-validated), PEM private keys |
| **Standard PII** | Emails (obfuscation-decoded), phones (international via libphonenumber) |

### 🖼 Evidence & Media

- **Three-tier media downloader** — yt-dlp (1000+ platforms) → Selenium click-play → static HTML.
- **Full-page screenshots** — Playwright (preferred) → Selenium Firefox fallback.
- **File downloader** — batch by extension; auto extracts PDF/EXIF/DOCX/XLSX metadata.

### 📤 Export

| Format | Details |
|---|---|
| **Excel** | Styled header, alternating rows, clickable hyperlinks, auto-fit columns |
| **CSV** | Plain comma-separated for spreadsheet import |
| **JSON** | Structured object array for programmatic processing |
| **HTML** | Self-contained styled report for sharing |

---

## Installation

```bash
# 1. Clone
git clone https://github.com/kahz12/scannus.git
cd scannus

# 2. Create venv
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 3. Install
pip install -r requirements.txt
```

### Platform notes

| Platform | Status |
|---|---|
| **Linux / Windows** | Primary — all features available |
| **macOS** | Supported |
| **Termux / Android (aarch64)** | Alternative — Maigret unavailable (no `aiohttp==3.8.x` wheel); Sherlock works |

**Requirements:** Python 3.10+, Firefox (for Selenium features), Ollama daemon (only if using local LLM).

---

## Configuration

Run the interactive wizard to populate `.env`:

```bash
python main.py -c
```

### Environment variables

| Variable | Service | Required for |
|---|---|---|
| `API_KEY_GOOGLE` · `SEARCH_ENGINE_ID` | Google Cloud / Programmable Search | Google Custom Search |
| `BRAVE_API_KEY` | Brave Search API | Brave engine |
| `GOOGLE_API_KEY_FOR_GEMINI` | Google AI Studio | Gemini provider |
| `OPENAI_API_KEY` | OpenAI Platform | GPT-4o provider |
| `ANTHROPIC_API_KEY` | Anthropic Console | Claude provider |
| `OLLAMA_HOST` · `OLLAMA_MODEL` | Local Ollama daemon | Ollama provider |
| `HIBP_API_KEY` | Have I Been Pwned | Account + paste lookups (paid) |
| `SHODAN_API_KEY` | Shodan | Host service banner lookups |
| `SCANNUS_CACHE_DISABLE` | — set to `1` to bypass cache | Debugging |

> DuckDuckGo, Pwned Passwords k-anon, domain-only HIBP, crt.sh, and Wayback Machine require **no** keys.

---

## Usage

### Interactive TUI

```bash
python main.py        # interactive by default
python main.py -i     # explicit
```

**Main menu:**

```
Guided Search           Name · Username · Email · Phone
Direct Search           Raw query or Google Dork
AI Dork Generator       LLM-assisted dork creation
AI Query Planner        ReAct-style multi-tool plan
Reverse Image Lookup    TinEye · Bing · Yandex · manual URLs
Web Technology Scan     Tech stack fingerprinting
Username Enumeration    Sherlock · 400+ sites
Domain Recon            WHOIS · DNS · TLS · headers · subdomains
Breach & Leak Check     HIBP: accounts · domains · passwords
Load Saved Case         Resume a previous investigation
Configure API Keys      Edit .env credentials
```

### Command-Line Examples

```bash
# Basic & guided search
python main.py -q 'site:linkedin.com "project manager" "New York"'
python main.py -n "John Doe" -u "jdoe88" -e "john@corp.com"
python main.py -gd "Find exposed admin panels on .gov domains"

# AI-driven multi-step investigation
python main.py -p "Investigate breaches affecting acme.com and dump PII leads"

# Domain reconnaissance
python main.py --recon example.com

# Breach intelligence
python main.py --hibp-account target@example.com
python main.py --hibp-domain example.com
python main.py --hibp-breach Adobe
python main.py --hibp-password                # interactive, hidden input

# Wayback Machine
python main.py -q "site:archive.org"
# (interactive menu offers snapshot fetch, PII extraction, diff)

# Username enumeration
python main.py --username-enum jdoe88 --enum-backend sherlock

# Reverse image
python main.py -rev https://example.com/photo.jpg

# Cache management
python main.py --cache-stats
python main.py --cache-clear wayback          # or omit for full wipe

# Export
python main.py -q "query" --excel out.xlsx --json out.json
```

### Full CLI flag reference

| Group | Flags |
|---|---|
| **Main** | `-h` · `-q` · `-c` · `-i` |
| **Search** | `-n` · `-u` · `-e` · `-t` · `-b` · `--engine` · `--deep` · `--pages` · `--start-page` · `--lang` |
| **AI / NLP** | `-gd "DESC"` · `-p "GOAL"` |
| **Recon** | `--recon DOMAIN` · `--username-enum HANDLE` · `--enum-backend` |
| **Breach (HIBP)** | `--hibp-account` · `--hibp-domain` · `--hibp-breach` · `--hibp-password` |
| **Media / image** | `--media-scrape URL` · `-rev URL` |
| **Cache** | `--cache-stats` · `--cache-clear [NS]` |
| **Cases** | `--load-case` |
| **Export** | `--excel` · `--csv` · `--json` · `--html` · `--download TYPES` · `--metadata` |

### Result navigation

| Input | Action |
|---|---|
| `<ID>` | Open per-URL analysis sub-menu |
| `n` / `p` / `j <N>` / `all` / `page` | Pagination controls |
| `media <ID,…>` | Batch media download |
| `save` · `excel` · `exit` | Persist · export · quit |

---

## Project Structure

```
ScannUs/
├── main.py                        # Entry point — CLI dispatch
├── requirements.txt
│
├── cli/
│   ├── ui.py                      # Rich theme, console helpers
│   ├── parser.py                  # Argparse + styled help
│   ├── menus.py                   # Interactive TUI menus
│   └── actions.py                 # CLI action handlers
│
├── core/
│   ├── config.py                  # Directories, .env wizard
│   ├── ai_agent.py                # 4 providers + planner + 22 dispatchers
│   ├── cache.py                   # SQLite cache (WAL, namespaced TTLs)
│   ├── case_manager.py            # Save / load / update / delete cases
│   ├── database.py                # SQLite DAO
│   └── state.py
│
├── search/
│   ├── smart_search.py            # PII + secret extraction (25+ patterns)
│   ├── reverse_image.py           # Multi-engine orchestrator
│   ├── reverse_image_engines.py   # TinEye · Bing · Yandex · manual
│   ├── username_enum.py           # Sherlock / Maigret wrapper
│   └── engines/
│       ├── googlesearch.py · duckduckgosearch.py · bravesearch.py
│       └── cache.py               # Backward-compat shim → core/cache
│
├── analysis/
│   ├── web_analyzer.py            # Fetch + clean + chunk + summarise
│   ├── tech_scanner.py            # Wappalyzer + WebTech fingerprinting
│   ├── advanced_osint.py          # Screenshots · Wayback fetch/diff
│   ├── domain_osint.py            # WHOIS · DNS · TLS · headers · crt.sh
│   └── hibp.py                    # Have I Been Pwned integration
│
└── utils/
    ├── media_downloader.py        # yt-dlp → Selenium → static HTML
    ├── results_parse.py           # Excel / CSV / JSON / HTML export
    └── file_download.py           # Batch download + metadata extraction
```

---

## Cache & Storage

### Persistent SQLite cache

All upstream calls flow through `core/cache.py` — a single `cache.db` shared by every namespace, with WAL journal mode for concurrent process access.

| Namespace | TTL | Contents |
|---|---|---|
| `search` | 24h | SERP results |
| `http_text` | 6h | Cleaned page content |
| `whois` | 7d | Registry data |
| `dns` | 1h | DNS records |
| `wayback` | 30d | Archive snapshots (immutable) |
| `crtsh` | 24h | CT-log subdomains |
| `hibp_account` | 12h | Per-email breach lookups |
| `hibp_breach` | 7d | Breach metadata |
| `hibp_password` | 30d | k-anonymity ranges |

### Output directory

```
outputs/
├── cache/cache.db        # Persistent SQLite cache
├── cases/cases.db        # Investigation case database
├── downloads/            # Files by MIME type
├── media/                # ZIP archives from --media-scrape
├── reports/              # Excel · CSV · JSON · HTML exports
├── screenshots/          # Full-page PNG screenshots
└── graphs/               # Pyvis entity relationship graphs
```

---

## Disclaimer

ScannUs is intended strictly for **educational purposes, authorised security research, and lawful open-source intelligence gathering**. Users assume full responsibility for compliance with all applicable local, national, and international laws.

**Do not use ScannUs against systems, accounts, or data for which you do not have explicit authorisation.**

---

<div align="center">

Developed by **Ale**

</div>
