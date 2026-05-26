# ScannUs — User Guide

A comprehensive walkthrough of every feature, workflow, and configuration option in ScannUs.

---

## Table of Contents

1. [Getting Started](#1-getting-started)
   - 1.1 [Installation](#11-installation)
   - 1.2 [First Run](#12-first-run)
   - 1.3 [Configuration Wizard](#13-configuration-wizard)
2. [Core Concepts](#2-core-concepts)
   - 2.1 [Interactive Mode vs CLI Mode](#21-interactive-mode-vs-cli-mode)
   - 2.2 [Cases](#22-cases)
   - 2.3 [The Persistent Cache](#23-the-persistent-cache)
   - 2.4 [AI Providers](#24-ai-providers)
3. [Search](#3-search)
   - 3.1 [Direct Search](#31-direct-search)
   - 3.2 [Guided Search](#32-guided-search)
   - 3.3 [Engines Compared](#33-engines-compared)
   - 3.4 [Pagination & Languages](#34-pagination--languages)
4. [AI Features](#4-ai-features)
   - 4.1 [Choosing a Provider](#41-choosing-a-provider)
   - 4.2 [AI Dork Generator](#42-ai-dork-generator)
   - 4.3 [AI Query Planner (ReAct)](#43-ai-query-planner-react)
   - 4.4 [The Tool Catalog](#44-the-tool-catalog)
5. [Per-URL Analysis](#5-per-url-analysis)
   - 5.1 [Summarise Content](#51-summarise-content)
   - 5.2 [Extract PII](#52-extract-pii)
   - 5.3 [Web Technology Scan](#53-web-technology-scan)
   - 5.4 [Download File](#54-download-file)
   - 5.5 [Download Media](#55-download-media)
   - 5.6 [Capture Screenshot](#56-capture-screenshot)
   - 5.7 [Wayback Machine](#57-wayback-machine)
   - 5.8 [Deep AI Analysis](#58-deep-ai-analysis)
   - 5.9 [Entity Relationship Graph](#59-entity-relationship-graph)
   - 5.10 [Deep Scraping (JavaScript Render)](#510-deep-scraping-javascript-render)
6. [Reverse Image Search](#6-reverse-image-search)
7. [Username Enumeration](#7-username-enumeration)
8. [Domain & Network OSINT](#8-domain--network-osint)
9. [Breach & Leak Intelligence (HIBP)](#9-breach--leak-intelligence-hibp)
10. [Wayback Machine Deep Dive](#10-wayback-machine-deep-dive)
11. [PII & Secret Extraction Reference](#11-pii--secret-extraction-reference)
12. [Media Downloader](#12-media-downloader)
13. [Case Management](#13-case-management)
14. [Export Formats](#14-export-formats)
15. [Cache Management](#15-cache-management)
16. [Investigation Recipes](#16-investigation-recipes)
17. [Troubleshooting](#17-troubleshooting)
18. [FAQ](#18-faq)
19. [Glossary](#19-glossary)

---

## 1. Getting Started

### 1.1 Installation

#### Linux / macOS / Windows

```bash
git clone https://github.com/kahz12/scannus.git
cd scannus
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

#### Termux (Android)

ScannUs runs on Termux but with a few caveats:

```bash
pkg install python rust firefox
pip install -r requirements.txt
```

| Module | Termux status |
|---|---|
| Sherlock | ✅ Pure Python, works |
| Maigret | ❌ Pins `aiohttp==3.8.x` with no aarch64-android wheel |
| Playwright | ❌ No Chromium for Android arm — falls back to Selenium |
| Selenium + geckodriver | ✅ `pkg install geckodriver` |
| pycryptodome | ✅ For EIP-55 Ethereum validation |

#### System dependencies

| Tool | Required for |
|---|---|
| **Firefox + geckodriver** | Selenium screenshots, deep scraping, reverse image, click-play media |
| **Chromium + Playwright** | Preferred screenshot engine (faster, more reliable) |
| **ollama** (optional) | Local LLM provider — only if using `Ollama` AI backend |

Install Playwright browsers (optional but recommended):

```bash
playwright install chromium
```

### 1.2 First Run

```bash
python main.py
```

The first run will:

1. Create the `outputs/` directory tree.
2. Check for `.env` — if missing, prompt you to run the wizard.
3. Print the gradient banner showing which API keys it detected.
4. Drop you into the interactive TUI main menu.

If you'd rather configure first:

```bash
python main.py -c
```

### 1.3 Configuration Wizard

The wizard (`python main.py -c`) walks you through 7 sections, prompting one key at a time. Press Enter to skip any field.

```
┌─ Google Custom Search API ───────────────────────
│   API_KEY_GOOGLE      (from console.cloud.google.com)
│   SEARCH_ENGINE_ID    (from cse.google.com)
├─ Google AI (Gemini) ─────────────────────────────
│   GOOGLE_API_KEY_FOR_GEMINI (from aistudio.google.com)
├─ Brave Search API ───────────────────────────────
│   BRAVE_API_KEY       (from api.search.brave.com)
├─ Have I Been Pwned (HIBP) ───────────────────────
│   HIBP_API_KEY        (from haveibeenpwned.com/API/Key)
├─ Anthropic Claude ───────────────────────────────
│   ANTHROPIC_API_KEY   (from console.anthropic.com)
├─ Ollama (local LLM) ─────────────────────────────
│   OLLAMA_HOST         (default: http://localhost:11434)
│   OLLAMA_MODEL        (default: llama3)
└─ OpenAI ─────────────────────────────────────────
    OPENAI_API_KEY      (from platform.openai.com)
```

All values are written to `.env` in the project root. You can edit them by hand at any time.

#### Minimum viable configuration

You can use ScannUs with **zero API keys**:

- ✅ DuckDuckGo search
- ✅ HIBP password k-anonymity check (free)
- ✅ HIBP domain breaches (free)
- ✅ HIBP single breach lookup (free)
- ✅ crt.sh subdomain enumeration
- ✅ Wayback Machine
- ✅ WHOIS + DNS + TLS + HTTP headers
- ✅ Username enumeration via Sherlock
- ✅ Web technology fingerprinting
- ✅ Reverse image — manual fallback URLs

To unlock the full power, add at minimum a Gemini key (free tier) and a Google Custom Search key.

---

## 2. Core Concepts

### 2.1 Interactive Mode vs CLI Mode

ScannUs has two equally powerful interfaces:

**Interactive TUI** — best for investigations where each step informs the next:

```bash
python main.py            # default
python main.py -i         # explicit
```

**CLI mode** — best for scripting, automation, and one-off lookups:

```bash
python main.py --recon example.com --json out.json
python main.py --hibp-account target@example.com
```

Every CLI flag has an equivalent menu entry, and vice versa. The TUI internally dispatches to the same functions as the CLI.

### 2.2 Cases

A **case** is a named investigation — your query, the engine used, all the results that came back, and a creation timestamp. Cases live in a SQLite database at `outputs/cases/cases.db`.

#### Saving a case

After a search returns results, type `save` at the result prompt. You'll be asked for a name. If the name already exists, you'll be prompted to confirm overwrite.

#### Loading a case

```bash
python main.py --load-case
```

Or from the main menu → "Load Saved Case". You'll see a list of cases; pick one to restore results and drop into the analysis menu.

#### Case schema

```sql
CREATE TABLE cases (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    UNIQUE NOT NULL,
    query_data TEXT,             -- JSON: {"type": "direct", "value": "..."}
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id     INTEGER NOT NULL,
    result_id   INTEGER,
    title       TEXT,
    description TEXT,
    link        TEXT,
    FOREIGN KEY (case_id) REFERENCES cases (id) ON DELETE CASCADE
);
```

### 2.3 The Persistent Cache

Every expensive upstream call routes through a single SQLite cache at `outputs/cache/cache.db`. The cache:

- **Persists across sessions** — restart your terminal, the cache survives.
- **Uses WAL journal mode** — multiple processes can share it.
- **Has per-namespace TTLs** — different content types expire at different rates.
- **Stores JSON** — datetimes are stringified automatically.

#### Namespaces & TTLs

| Namespace | TTL | What's cached |
|---|---|---|
| `search` | 24h | SERP results from all engines |
| `http_text` | 6h | Cleaned page text |
| `whois` | 7d | Registrar metadata |
| `dns` | per-record-type | A/AAAA/CNAME 1h · TXT 3h · MX/NS/SOA/CAA 24h |
| `wayback` | 30d | Archive snapshots (immutable anyway) |
| `crtsh` | 7d | CT-log subdomain enumeration (logs are append-only) |
| `hibp_account` | 12h | Per-email breach + paste lookups |
| `hibp_breach` | 7d | Breach metadata, domain breaches, full catalog |
| `hibp_password` | 30d | k-anonymity SHA-1 ranges |

#### Bypassing the cache temporarily

```bash
SCANNUS_CACHE_DISABLE=1 python main.py --recon example.com
```

When disabled, all reads return `None` and writes are no-ops — useful for debugging.

#### Inspecting the cache

```bash
python main.py --cache-stats
```

Returns:

```
hits:        42
misses:      18
hit_ratio:   70.0%
rows:        103
by_namespace: {'search': 24, 'whois': 4, 'wayback': 41, ...}
db_path:     /path/to/outputs/cache/cache.db
db_size:     487424
disabled:    False
```

#### Clearing the cache

```bash
python main.py --cache-clear              # wipe everything
python main.py --cache-clear wayback      # one namespace only
python main.py --cache-clear hibp_account # invalidate breach lookups
```

### 2.4 AI Providers

ScannUs supports four AI providers, all behind a unified `generate(prompt)` + `stream(prompt)` contract:

| Provider | Model | Cost | Setup |
|---|---|---|---|
| **Google Gemini** | `gemini-2.0-flash` | Free tier | `GOOGLE_API_KEY_FOR_GEMINI` |
| **OpenAI** | `gpt-4o` | Paid | `OPENAI_API_KEY` |
| **Anthropic** | `claude-sonnet-4-6` | Paid | `ANTHROPIC_API_KEY` |
| **Ollama** | `llama3` (configurable) | Free (local) | `OLLAMA_HOST` daemon |

Providers stream tokens — output appears incrementally rather than all-at-once at the end.

Override any model via env var:

```bash
ANTHROPIC_MODEL=claude-opus-4-7 python main.py -i
OLLAMA_MODEL=qwen2.5:7b python main.py -i
```

---

## 3. Search

### 3.1 Direct Search

The most common entry point. Pass any query string with `-q`:

```bash
python main.py -q "OSINT tools"
python main.py -q 'site:linkedin.com "project manager" "New York"'
python main.py -q 'filetype:xlsx "price list" "electronic products"'
```

Google Dork operators are passed through verbatim:

| Operator | Effect |
|---|---|
| `site:` | Restrict to a domain |
| `filetype:` | Restrict to file extension |
| `intitle:` | Match in `<title>` |
| `inurl:` | Match in URL path |
| `"exact phrase"` | Verbatim match |
| `-exclude` | Exclude terms |
| `AND` / `OR` | Boolean combinators |

### 3.2 Guided Search

For people-OSINT, build a compound `AND` query interactively or via flags:

```bash
python main.py -n "John Doe" -u "jdoe88" -e "john@corp.com" -t "+1-555-0123"
```

The resulting query is:

```
"John Doe" AND "jdoe88" AND "john@corp.com" AND "+1-555-0123"
```

If `-e` or `-t` is present, ScannUs automatically switches to **deep extraction mode** — crawls each result URL and runs PII extraction on the content.

Available guided flags:

| Flag | Short | Purpose |
|---|---|---|
| `--nombre` | `-n` | Full legal name |
| `--usuario` | `-u` | Username / handle |
| `--email` | `-e` | Email (triggers `--deep`) |
| `--telefono` | `-t` | Phone (triggers `--deep`) |
| `--buscar` | `-b` | Generic keyword |

### 3.3 Engines Compared

| Engine | Auth | Pros | Cons |
|---|---|---|---|
| **DuckDuckGo** | None | Free, no rate limits visible | HTML scraping — can break on layout changes |
| **Google CSE** | API key + CX | Highest quality results | 100 free queries/day, then $5 per 1000 |
| **Brave Search** | API key | Independent index, less Google-correlated | Smaller index than Google |

Pick at runtime:

```bash
python main.py -q "query" --engine duckduckgo    # default
python main.py -q "query" --engine google
python main.py -q "query" --engine brave
```

### 3.4 Pagination & Languages

```bash
python main.py -q "query" --pages 3              # fetch 3 pages
python main.py -q "query" --start-page 5         # start from page 5
python main.py -q "query" --lang lang_en         # English only
python main.py -q "query" --lang lang_es         # Spanish (default)
```

---

## 4. AI Features

### 4.1 Choosing a Provider

When the TUI needs an AI agent, it shows a picker. From the CLI, the provider is selected lazily — only the agent you need spins up.

**Decision matrix:**

| You need… | Pick |
|---|---|
| Best free option, fast iteration | Gemini |
| Highest analytical quality | Claude or GPT-4o |
| Air-gapped / privacy-sensitive | Ollama |
| Lowest cost per token at high quality | Claude Sonnet 4.6 |
| Strongest tool-use / structured-output | Claude or GPT-4o |

### 4.2 AI Dork Generator

Converts plain English into a precise Google Dork:

```bash
python main.py -gd "Find Excel price lists of electronics companies"
```

Streams the dork live to your terminal:

```
filetype:xlsx "price list" "electronic" OR "electronics"
```

Or via TUI: Main menu → **AI Dork Generator**.

**Tips for good descriptions:**

- Mention file types explicitly: "PDFs of contracts", "Excel price lists"
- Mention domains/TLDs: ".gov", ".edu.co"
- Mention exclusions: "exclude marketing sites"

### 4.3 AI Query Planner (ReAct)

The planner takes a natural-language goal and produces a **multi-step investigation plan** composed of whitelisted tool calls. Each step is interactively confirmable, and the planner can re-plan after each observation.

```bash
python main.py -p "Investigate breaches affecting acme.com and find leaked PII"
```

A typical plan looks like:

```
Plan summary: Recon the target domain, enumerate breach exposure,
              then crawl for leaked PII surface.

Step 1/5 · domain_recon
  why:    Establish baseline (WHOIS, DNS, TLS, headers, subdomains)
  expect: Tech stack and infrastructure overview
  args:   {'target': 'acme.com'}
  Run this step? [Y/n]

Step 2/5 · hibp_domain
  why:    Check whether acme.com has been recorded in any breach
  ...
```

You can:

- **Accept** each step → it executes; results are summarised and printed.
- **Skip** a step → planner moves on.
- **Abort** mid-plan → ScannUs records observations and can re-plan.

The plan is stored in the current case so you can replay it later.

### 4.4 The Tool Catalog

The planner can only call whitelisted tools. As of this guide, 24 tools are exposed:

| Tool | Purpose |
|---|---|
| `search` | Run a SERP search |
| `deep_search` | Search + crawl + extract PII |
| `extract_pii` | Crawl one URL and extract PII |
| `tech_scan` | Fingerprint web tech |
| `username_enum` | Sherlock/Maigret enumeration |
| `email_enum` | Holehe ~120-service registration lookup |
| `phone_osint` | Offline number intelligence (carrier, region, line type) + footprint |
| `screenshot` | Full-page screenshot |
| `wayback` | Snapshot timeline |
| `wayback_fetch` | Fetch raw archived content |
| `wayback_extract` | PII extraction on a snapshot |
| `wayback_diff` | Diff two snapshots |
| `summarize_url` | AI summary of a URL |
| `domain_recon` | Full domain OSINT sweep |
| `whois` | WHOIS lookup |
| `dns_records` | DNS records |
| `tls_certificate` | TLS cert inspection |
| `http_security_headers` | HTTP hardening headers |
| `subdomains` | crt.sh CT-log enumeration |
| `reverse_image` | Multi-engine reverse image |
| `hibp_account` | HIBP account breach lookup |
| `hibp_domain` | HIBP domain breaches (free) |
| `hibp_breach` | Single breach metadata (free) |
| `hibp_password` | Pwned Passwords k-anon (free) |

Each tool returns `{status, summary, data}`. The planner sees the summary and uses it to inform the next step.

---

## 5. Per-URL Analysis

After a search, you'll see a paginated table. Type a result's ID to open the **URL Analysis Sub-Menu**, which gives you 10 deep-dive options for that single URL.

### 5.1 Summarise Content

```
URL Analysis → Summarize content (AI)
```

Fetches the page, extracts clean text (trafilatura → readability → BeautifulSoup pipeline), chunks if needed (12 KB windows, 500-char overlap), and feeds each chunk through the selected AI provider. Output streams to terminal and is rendered in a green-bordered panel.

### 5.2 Extract PII

```
URL Analysis → Extract PII
```

Fetches the page and runs the **secret + PII regex battery** against the text. See [PII & Secret Extraction Reference](#11-pii--secret-extraction-reference) for the full list of detected categories.

Output:

```
╭──────────────────────────────────────────────────╮
│ Extracted PII                                    │
├──────────────────────────────────────────────────┤
│ Emails       │ alice@acme.com                    │
│              │ bob@acme.com                      │
│ Phones       │ +1-555-0123                       │
│ Iban         │ DE89370400440532013000            │
│ Aws_keys     │ AKIAIOSFODNN7EXAMPLE              │
│ Github_pat   │ ghp_aBcDeFgHiJ…                   │
│ Btc_wallets  │ 1A1zP1eP5QGefi2DMPTfTL5SLmv7…     │
╰──────────────────────────────────────────────────╯
```

### 5.3 Web Technology Scan

```
URL Analysis → Scan web technologies
```

Runs Wappalyzer (preferred) or webtech (fallback) against the URL and prints a categorised table:

```
CMS              WordPress 6.4
Framework        React 18.2
Web server       nginx 1.25
CDN              Cloudflare
Analytics        Google Analytics, Mixpanel
Tag managers     Google Tag Manager
```

Also available standalone:

```bash
python main.py -i    # then choose "Web Technology Scan"
```

### 5.4 Download File

```
URL Analysis → Download file
```

Direct HTTP download of the URL with automatic metadata extraction:

| File type | Metadata extracted |
|---|---|
| PDF | Title, author, creator, producer, creation date, page count |
| DOCX | Core properties (title, author, last-modified-by, etc.) |
| XLSX | Workbook properties |
| Images | EXIF (camera model, GPS, timestamp, software) |

Saved to `outputs/downloads/<type>/`.

### 5.5 Download Media

```
URL Analysis → Download media
```

Triggers the **three-tier media downloader** (see [Section 12](#12-media-downloader)). You'll be asked:

1. **Media type** — `all`, `images`, `videos`, or `audio`
2. **Use Selenium for JS-rendered pages?** — `y`/`N`

Output: a structured ZIP archive in `outputs/media/`.

### 5.6 Capture Screenshot

```
URL Analysis → Capture screenshot
```

Auto-selects screenshot engine:

1. **Playwright (Chromium)** — preferred. Most reliable; handles modern web.
2. **Selenium (Firefox headless)** — fallback. Resizes the window to full document height for a single-shot full-page PNG.

Saved to `outputs/screenshots/<host_slug>_<timestamp>.png`.

### 5.7 Wayback Machine

```
URL Analysis → Wayback Machine history
```

Queries the Internet Archive CDX API for the URL's snapshot timeline. Renders a table of timestamps + status codes + mime types.

For deeper Wayback workflows, see [Section 10](#10-wayback-machine-deep-dive).

### 5.8 Deep AI Analysis

```
URL Analysis → Deep AI analysis
```

Like Summarise, but with an OSINT-focused prompt. The AI is asked to extract:

- People, organisations, locations mentioned
- Implicit relationships ("X works for Y", "A reports to B")
- Investigation leads ("Y's email is mentioned — try the format pattern")
- Key intelligence points

Renders in a yellow-bordered panel.

### 5.9 Entity Relationship Graph

```
URL Analysis → Entity relationship graph
```

The AI extracts entities and their relationships in structured JSON; Pyvis renders an interactive HTML graph. Output: `outputs/graphs/graph_<host>.html`.

Open in any browser to explore, zoom, drag nodes.

### 5.10 Deep Scraping (JavaScript Render)

```
URL Analysis → Deep scraping
```

For Single-Page Applications and JS-heavy sites that static HTTP can't reach:

1. Spins up headless Firefox via Selenium.
2. Loads the URL, waits for `document.readyState === 'complete'`.
3. Scrolls to bottom (lazy-load triggers).
4. Extracts the rendered DOM text.
5. Runs PII extraction against the rendered text.

Slower than static fetching but reveals content that's otherwise invisible to scrapers.

---

## 6. Reverse Image Search

Multi-engine, multi-tier orchestrator. Always returns *something* because the manual-URL tier never fails.

```bash
python main.py -rev https://example.com/photo.jpg
```

Or via TUI: Main menu → **Reverse Image Lookup**.

### Tier breakdown

| Tier | Engine | Auth | What it returns |
|---|---|---|---|
| 1 | **TinEye** | `TINEYE_PUBLIC_KEY` + `TINEYE_PRIVATE_KEY` | Exact-match results, mirror domains |
| 2 | **Bing Visual Search** | `BING_VISUAL_API_KEY` | Visually similar images |
| 3 | **Yandex** | None (HTML scraping via Selenium) | Strong for face matching, EE-region content |
| 4 | **Manual fallback** | None | URLs to Google Lens, Bing, Yandex, TinEye, SauceNAO with the image pre-filled |

### Sample output

```
Reverse image: 14 entries (tineye×2, bing×3, yandex×4, manual×5)
```

### Whitelisting engines

```bash
python main.py -rev https://example.com/photo.jpg
# (interactive — automatic)

# Or in a plan step:
{"tool": "reverse_image",
 "args": {"url": "https://example.com/photo.jpg",
          "engines": ["tineye", "yandex", "manual"]}}
```

---

## 7. Username Enumeration

Check a username against 400+ (Sherlock) or 3000+ (Maigret) social sites.

```bash
python main.py --username-enum jdoe88
python main.py --username-enum jdoe88 --enum-backend sherlock
python main.py --username-enum jdoe88 --enum-backend maigret    # Linux/macOS only
python main.py --username-enum jdoe88 --enum-backend auto       # prefer Sherlock
```

Or TUI: Main menu → **Username Enumeration**. You'll be prompted for:

1. The username/handle
2. Backend (auto/sherlock/maigret)
3. Per-site timeout (default 20s)

### Comparison

| Backend | Sites | Speed | Termux | Python 3.13 |
|---|---|---|---|---|
| **Sherlock** | ~400 | Fast (concurrent) | ✅ | ✅ |
| **Maigret** | ~3000 | Slower (more thorough) | ❌ | ⚠️ Pins aiohttp 3.8.x |

Results are rendered in a table:

```
╭─────────────┬───────────────────────────────────╮
│ Site        │ URL                               │
├─────────────┼───────────────────────────────────┤
│ GitHub      │ https://github.com/jdoe88         │
│ Twitter     │ https://twitter.com/jdoe88        │
│ Reddit      │ https://reddit.com/user/jdoe88    │
╰─────────────┴───────────────────────────────────╯
```

### 7.1 Email Enumeration (Holehe)

The email counterpart to Sherlock/Maigret. Given an email, **Holehe** probes
~120 services (Instagram, Twitter, Pinterest, Spotify, Adobe, Pornhub, …) via
their password-reset endpoints and reports where the address is registered —
*without sending any email to the target*.

```bash
python main.py --email-enum target@example.com           # claimed services only
python main.py --email-enum target@example.com --email-enum-all   # full report
```

TUI: Main menu → **Email Enumeration**.

**How it differs from related tools:**

| Tool | What it answers |
|---|---|
| `--hibp-account` | *Has this email been leaked in a known data breach?* |
| `--email-enum` (Holehe) | *Where is this email currently registered today?* |
| `-e/--email` (deep PII) | *What does the web say about this email — pages, mentions, PII?* |

Results cache for 12h under the `email_enum` namespace, so re-running on the
same address is instant.

**Limitations:**

- Per-site detectors rot as services change their reset UX — expect occasional
  false negatives. Pin a known-good `holehe` version in `requirements.txt`.
- Some sites silently rate-limit Holehe; results from a single run may
  under-report. Re-run after a few minutes if a known account isn't surfaced.
- **Do not** use this for bulk enumeration: rate limits + captchas will block you.

**Install:** `pip install holehe`. If absent, `--email-enum` prints a friendly
install hint and exits cleanly.

### 7.2 Phone Intelligence (libphonenumber)

The phone counterpart to username/email enumeration. Given a number, ScannUs
resolves everything knowable **offline** from Google's libphonenumber metadata —
validity, country/region, geographic location, carrier, time zones and line type
(mobile / fixed / VoIP / toll-free) — then generates an **OSINT footprint**:
ready-to-run search dorks (across the number's written forms) plus number-lookup
links (Truecaller, WhatsApp `wa.me`, Sync.me).

```bash
python main.py --phone-osint "+14155552671"      # international format preferred
```

TUI: Main menu → **Phone Intelligence**. You'll be prompted for the number and an
optional ISO-3166 region hint (e.g. `US`) for numbers written in national format.

Sample output:

```
╭───────────────┬──────────────────────╮
│ Field         │ Value                │
├───────────────┼──────────────────────┤
│ Valid         │ yes                  │
│ E.164         │ +14155552671         │
│ Region        │ US                   │
│ Location      │ San Francisco, CA    │
│ Carrier       │ —                    │
│ Line type     │ fixed line or mobile │
│ Time zones    │ America/Los_Angeles  │
╰───────────────┴──────────────────────╯
```

**How it differs from related tools:**

| Flag | What it answers |
|---|---|
| `--phone-osint` | *What can I learn about this number itself — region, carrier, line type — and where do I look next?* |
| `-t/--phone` (deep PII) | *What does the web say about this number — pages, mentions, PII?* |

**Notes:**

- **Offline, keyless, instant.** libphonenumber bundles its own metadata, so there
  is no network call, no API key, and (unlike the enumerators) no cache or rate
  limit. It runs everywhere, including Termux.
- Carrier data is sparse for some regions (libphonenumber only ships carrier maps
  for mobile ranges in supported countries) — a blank carrier is normal.
- Invalid or unparseable input is reported with a warning and best-effort
  metadata rather than a crash.

**Footprint pivots** feed the Findings Hub: running a footprint search dork pools
its result URLs back into the session so you can chain
`phone → search → URLs → analyse / download`.

---

## 8. Domain & Network OSINT

```bash
python main.py --recon example.com
```

Runs the **full recon sweep** in one command:

```
┌─ WHOIS ─────────────────────────────────
│  Registrar: ICANN
│  Created:   1995-08-13
│  Expires:   2026-08-12
│  ...
├─ DNS records ──────────────────────────
│  A      →  93.184.216.34
│  AAAA   →  2606:2800:220:1:248:1893:25c8:1946
│  MX     →  10 mail.example.com
│  NS     →  a.iana-servers.net, b.iana-servers.net
│  ...
├─ Email security ───────────────────────
│  SPF       →  v=spf1 -all
│  DMARC     →  v=DMARC1; p=reject; rua=mailto:...
│  DKIM hint →  default._domainkey.example.com  (not found)
├─ TLS certificate ──────────────────────
│  Subject   →  www.example.com
│  SANs      →  www.example.com, example.com
│  Valid until: 2026-03-15  (245 days left)
│  Cipher    →  TLS_AES_256_GCM_SHA384  (TLSv1.3)
├─ HTTP security headers ────────────────
│  Score: 6/10
│  HSTS       ✓   max-age=31536000
│  CSP        ✓   present
│  COOP       ✗   missing
│  COEP       ✗   missing
│  X-Frame    ✓   SAMEORIGIN
│  ...
├─ Subdomains (crt.sh) ──────────────────
│  47 subdomains discovered
│  api.example.com, dev.example.com, staging…
└─ Shodan host lookup ───────────────────
   Ports: 80, 443, 8080
   Services: nginx, ssh
```

### Individual primitives

You can run each piece in isolation from the TUI:

| Menu entry | What it does |
|---|---|
| Full recon | All seven |
| WHOIS | Registrar metadata only |
| DNS records | All record types |
| Email security (SPF/DMARC) | Mail authentication |
| TLS certificate | Cert chain + validity |
| HTTP security headers | Hardening header scoring |
| Subdomains (crt.sh) | Passive CT-log enumeration |
| Shodan host lookup | Service banners (needs `SHODAN_API_KEY`) |

### Cache TTLs for recon

WHOIS rarely changes (7d cached). DNS changes frequently (1h cached). crt.sh appends only (24h cached).

---

## 9. Breach & Leak Intelligence (HIBP)

ScannUs integrates the full Have I Been Pwned API surface plus the free Pwned Passwords k-anonymity endpoint.

### 9.1 Account Lookup (paid)

```bash
python main.py --hibp-account target@example.com
```

Requires `HIBP_API_KEY`. Returns:

- **Breaches** containing this email
- **Pastes** referencing this email (Pastebin, GitHub Gist, etc.)

Sample output:

```
╭──────────────────────────────────────────────────────────────╮
│ Breaches for target@example.com  (3 hits)                    │
├──────────┬────────────┬──────────┬─────────────┬─────────────┤
│ Name     │ Domain     │ Date     │ Accounts    │ Data        │
├──────────┼────────────┼──────────┼─────────────┼─────────────┤
│ Adobe    │ adobe.com  │ 2013-10  │ 152,445,165 │ Email…      │
│ LinkedIn │ linkedin.. │ 2012-05  │ 164,611,595 │ Email…      │
│ Dropbox  │ dropbox..  │ 2012-07  │  68,648,009 │ Email…      │
╰──────────┴────────────┴──────────┴─────────────┴─────────────╯
```

### 9.2 Domain Lookup (free)

```bash
python main.py --hibp-domain example.com
```

No API key required. Lists every recorded breach affecting the domain. Great for a quick company-hygiene check.

### 9.3 Single Breach Details (free)

```bash
python main.py --hibp-breach Adobe
python main.py --hibp-breach LinkedIn
```

Returns full breach metadata including the description prose, sensitivity flag, and exact list of data classes that were leaked.

### 9.4 Pwned Passwords (free, safe)

```bash
python main.py --hibp-password
```

You'll be prompted for a password with **hidden input** (no terminal echo). The plaintext is hashed locally with SHA-1; only the first 5 hex characters of the hash are sent to `api.pwnedpasswords.com`. The full hash never leaves your process.

Sample outputs:

```
✔  Password not found in any known HIBP breach corpus.
```

```
⚠  Password seen in HIBP corpus: 3 time(s) — change it.
```

```
✘  Password seen in HIBP corpus: 9,999,999 time(s) — do NOT use it anywhere.
```

### 9.5 Privacy guarantee

| What never happens | What does happen |
|---|---|
| Plaintext password leaves your machine | SHA-1 hash computed locally |
| Full hash sent to HIBP | First 5 hex chars sent to HIBP |
| Plaintext logged anywhere | Plaintext discarded immediately after hashing |

You can verify this by running a packet sniffer (`tcpdump`, `wireshark`) while invoking `--hibp-password`. Only the prefix appears in outbound traffic.

---

## 10. Wayback Machine Deep Dive

### 10.1 Timeline lookup

```bash
python main.py -q "site:example.com"
# select a result → URL Analysis → Wayback Machine history
```

Returns a table of snapshots: timestamp, status code, MIME type.

### 10.2 Snapshot fetch

Available via the AI Query Planner with the `wayback_fetch` tool, or programmatically:

```python
from analysis.advanced_osint import wayback_fetch_snapshot
snap = wayback_fetch_snapshot("https://example.com", "20200615")
# {timestamp, date, archive_url, status, mime, size, text}
```

Accepted timestamp formats:

| Input | Meaning |
|---|---|
| `latest` | Most recent snapshot |
| `earliest` | First-ever snapshot |
| `2020` | Closest snapshot to year 2020 |
| `2020-06` | Closest to June 2020 |
| `20200615` | Date (YYYYMMDD) |
| `20200615120000` | Full 14-digit CDX timestamp |

### 10.3 Snapshot PII extraction

Tool: `wayback_extract`. Fetches a snapshot and runs the full PII/secret battery on it. Surfaces identifiers that have been scrubbed from the live site.

```
Plan step: {
  "tool": "wayback_extract",
  "args": {"url": "https://example.com/team", "timestamp": "2019"}
}
```

### 10.4 Snapshot diff

Tool: `wayback_diff`. Renders a unified diff between two snapshots:

```
{
  "tool": "wayback_diff",
  "args": {"url": "https://example.com/about",
           "ts_a": "2018", "ts_b": "latest"}
}
```

Output:

```
2018-01-15 -> 2024-08-03: +127 -83
+ Phone: +1-555-9090
+ Email: contact@newco.example
- Phone: +1-555-0123
- Office: 123 Old Street
```

Snapshots with identical content fingerprints (SHA-256) are flagged with `(identical)`.

---

## 11. PII & Secret Extraction Reference

ScannUs's extraction engine detects and validates **25+ identifier categories**. All validators check structure AND checksums where applicable.

### Standard PII

| Category | Validation |
|---|---|
| **Emails** | Regex + obfuscation decoding (`[at]`, `(dot)`, `&#64;`, spaced); false-positive filter excludes `noreply@*`, bots, test domains |
| **Phones** | libphonenumber (international, country-aware) |

### Government IDs

| Category | Validation |
|---|---|
| **US SSN** | Regex + rejects 000/666/9xx area, 00 group, 0000 serial |
| **Brazilian CPF** | Mod-11 two-digit checksum; rejects all-same digits |
| **Canadian SIN** | Luhn algorithm |
| **Argentine DNI/CUIT** | Structural |
| **Mexican RFC** | Structural |

### Financial

| Category | Validation |
|---|---|
| **IBAN** | Regex by country code + checksum |
| **Credit cards** | Luhn algorithm |

### Cloud & API secrets

| Category | Pattern |
|---|---|
| **AWS** | `AKIA…` / `ASIA…` + 16 chars |
| **GitHub PAT** | `ghp_` / `ghu_` / `gho_` / `ghr_` / `ghs_` + 36 chars; or `github_pat_` + 82 chars |
| **GitLab PAT** | `glpat-` + 20 chars |
| **Slack tokens** | `xoxa-` / `xoxb-` / `xoxp-` / `xoxr-` / `xoxs-` |
| **Stripe** | `(sk\|rk\|pk)_(live\|test)_…` |
| **Google API** | `AIza` + 35 chars |
| **Discord bot** | Token pattern |
| **Telegram bot** | `<digits>:<35 chars>` |
| **PEM private keys** | `-----BEGIN…PRIVATE KEY-----` |
| **JWTs** | Header decoded; requires valid `alg` field |

### Crypto wallets

| Category | Validation |
|---|---|
| **Bitcoin P2PKH/P2SH** | base58check decode + checksum |
| **Bitcoin Bech32** | Regex (`bc1q…`) |
| **Ethereum** | EIP-55 mixed-case Keccak-256 checksum (via pycryptodome) |

### Network

| Category | Validation |
|---|---|
| **Public IPv4** | stdlib `ipaddress`; filters private, loopback, link-local, multicast |
| **Public IPv6** | stdlib `ipaddress`; same filters |
| **MAC** | `XX:XX:XX:XX:XX:XX` or `XX-XX-…` |

### Example extraction output

```python
from search.smart_search import extract_information

text = """
Contact: alice@acme.com or call +1-555-0123
AWS: AKIAIOSFODNN7EXAMPLE
JWT: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
BTC: 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa
ETH: 0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed
"""

print(extract_information(text))
# {
#   "emails":      {"alice@acme.com"},
#   "phones":      {"+1-555-0123"},
#   "aws_keys":    {"AKIAIOSFODNN7EXAMPLE"},
#   "jwts":        {"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."},
#   "btc_wallets": {"1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"},
#   "eth_wallets": {"0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"},
# }
```

---

## 12. Media Downloader

Three-tier fallback strategy. Each tier is tried in order; if it fails, ScannUs moves to the next.

### Tier 1: yt-dlp (1000+ platforms)

The first attempt. Covers YouTube, Vimeo, TikTok, Twitter/X, Instagram, Twitch, Facebook, plus 1000+ niche sites. Handles HLS/DASH adaptive streams.

### Tier 2: Selenium click-play

For custom video players (proprietary CMS, paywalled players). ScannUs:

1. Spins up headless Firefox
2. Finds the `<video>` element
3. Clicks the play button
4. Waits 2 seconds for the `src` attribute to populate
5. Reads the resolved URL and downloads

### Tier 3: Static HTML

For pages with direct-linked `<video src="…">` that don't require JS. The simplest case.

### Usage

```bash
python main.py --media-scrape "https://example.com/gallery"
```

Or from the per-URL menu after a search → "Download media".

You'll be prompted:

1. **Media type** — `all`, `images`, `videos`, `audio`
2. **Use Selenium for JS-rendered pages?** — `y` if the site is JS-heavy

### Features

- **Concurrent** — `ThreadPoolExecutor` parallelises downloads
- **MIME-aware** — sorts into `images/`, `videos/`, `audio/` subdirectories
- **5 KB minimum** — filters out tracking pixels and empty responses
- **Retry with backoff** — 3 attempts with exponential delay
- **ZIP packaging** — final output is one structured archive

---

## 13. Case Management

### Saving

After running a search, type `save` at the results prompt:

```
> save
Enter case name: jdoe-investigation-2025-03
✓ Case 'jdoe-investigation-2025-03' saved (47 results)
```

If the name exists, you'll be asked to confirm overwrite:

```
Case 'jdoe-investigation-2025-03' already exists. Overwrite? [y/N]
```

### Loading

```bash
python main.py --load-case
```

Or main menu → **Load Saved Case**.

You'll see all cases with timestamps:

```
╭──┬───────────────────────────────────┬─────────────────────╮
│ #│ Name                              │ Created             │
├──┼───────────────────────────────────┼─────────────────────┤
│ 1│ jdoe-investigation-2025-03        │ 2025-03-14 18:42:01 │
│ 2│ acme-corp-recon                   │ 2025-03-10 09:15:22 │
│ 3│ phishing-campaign-leak            │ 2025-02-28 23:11:09 │
╰──┴───────────────────────────────────┴─────────────────────╯
```

Pick by ID; results are restored and the analysis menu opens.

### Updating

After loading a case, run additional searches. New results are merged. Type `save` again to update.

### Deleting

```
Main menu → Load Saved Case → pick → delete
```

Or directly via SQL:

```bash
sqlite3 outputs/cases/cases.db "DELETE FROM cases WHERE name='oldcase';"
```

---

## 14. Export Formats

### Excel (`.xlsx`)

```bash
python main.py -q "query" --excel results.xlsx
```

Features:
- Styled header row (bold, coloured background)
- Alternating row colours for readability
- Clickable hyperlinks in URL column
- Auto-fit column widths
- Saved to `outputs/reports/`

### CSV (`.csv`)

```bash
python main.py -q "query" --csv results.csv
```

Plain comma-separated. Opens cleanly in Excel, LibreOffice, pandas, R.

### JSON (`.json`)

```bash
python main.py -q "query" --json results.json
```

Structured array of objects:

```json
[
  {"id": 1, "title": "…", "description": "…", "link": "https://…"},
  {"id": 2, ...}
]
```

### HTML (`.html`)

```bash
python main.py -q "query" --html report.html
```

Self-contained styled report. No external assets — share it via email.

### Multiple at once

```bash
python main.py -q "query" --excel out.xlsx --json out.json --html out.html
```

---

## 15. Cache Management

### Inspect

```bash
python main.py --cache-stats
```

Shows hits, misses, hit ratio, row counts per namespace, DB file size.

### Clear

```bash
python main.py --cache-clear              # everything
python main.py --cache-clear search       # just SERPs
python main.py --cache-clear http_text    # just page content
python main.py --cache-clear hibp_account # invalidate breach lookups
python main.py --cache-clear wayback      # rare — archives are immutable
```

### Bypass

```bash
SCANNUS_CACHE_DISABLE=1 python main.py …
```

When the env var is set:
- All `get()` returns `None` (cache miss)
- All `set()` is a no-op
- Network calls always execute

### Programmatic access

```python
from core.cache import get_cache, cached_call

cache = get_cache()
cache.set("custom", "key1", {"data": "…"}, ttl=3600)
value = cache.get("custom", "key1")

# High-level helper
result = cached_call(
    "namespace",
    ["key", "parts"],
    lambda: expensive_function(),
    ttl=86400,
)
```

---

## 16. Investigation Recipes

End-to-end workflows combining multiple ScannUs features.

### Recipe 1: Investigating a leaked employee email

Goal: someone sent you `target@acme.com` as a phishing lead. Find out who they are, what they have access to, whether their credentials have leaked.

```bash
# 1. Has the email been in any breach?
python main.py --hibp-account target@acme.com

# 2. What's the company's security posture?
python main.py --recon acme.com

# 3. Are there other emails in the same pattern?
python main.py -q '"target" site:acme.com' --deep

# 4. Find the person's social accounts
python main.py --username-enum target

# 5. Save everything
python main.py -i      # → save → "target-acme-investigation"
```

Or let the AI planner orchestrate it:

```bash
python main.py -p "Investigate target@acme.com — breaches, social presence, company security posture, related PII"
```

### Recipe 2: Reconnaissance for a security engagement

```bash
python main.py --recon target.com --json recon.json
python main.py --hibp-domain target.com
python main.py -q "site:target.com filetype:pdf" --pages 3 --excel pdfs.xlsx
python main.py -q "site:target.com inurl:admin OR inurl:login"
```

### Recipe 3: Historic page recovery

A page has been edited; find what was removed.

```bash
python main.py -i
# Main menu → Direct Search → "site:target.com/team"
# Pick result → Wayback Machine history → note two interesting timestamps
# Use AI Query Planner with goal:
#   "Diff the team page between 2018 and now and extract any PII from the older version"
```

The planner will invoke `wayback_diff` and `wayback_extract` in sequence.

### Recipe 4: Verify a suspicious image

Someone sent you a photo of "[Person X]". Verify it's authentic.

```bash
python main.py -rev https://example.com/suspicious.jpg
```

The multi-engine reverse image returns hits from TinEye, Bing Visual, Yandex, plus manual lookup URLs. If TinEye returns earlier appearances of the image (with timestamps), the image isn't original.

### Recipe 5: Password hygiene audit

For a list of your own old passwords (stored offline), check each against HIBP without ever sending them anywhere:

```bash
for pw in "p1" "p2" "p3"; do
  echo "$pw" | python main.py --hibp-password
done
```

Each invocation hashes locally and only sends the 5-char prefix.

### Recipe 6: Investigation handoff

You've done some work. Now hand it off to a colleague.

```bash
python main.py -i
# Run searches, deep-extract URLs, build PII tables
# → save → "case-2025-03-acme"

# Then export everything for the colleague:
python main.py -q "<original query>" --excel handoff.xlsx --html handoff.html --json handoff.json
```

The colleague can later `--load-case` to pick up exactly where you left off.

---

## 17. Troubleshooting

### "Firefox not found" / "geckodriver missing"

Selenium needs Firefox + geckodriver in `PATH`. On Linux:

```bash
sudo apt install firefox-esr
# geckodriver: download from github.com/mozilla/geckodriver/releases
# place in /usr/local/bin/
```

On Termux:

```bash
pkg install firefox geckodriver
```

ScannUs will look for geckodriver at `/data/data/com.termux/files/usr/bin/geckodriver` first; otherwise it falls back to PATH-based discovery.

### "Playwright Chromium not installed"

```bash
playwright install chromium
```

If you can't install Playwright (e.g. Termux), ScannUs falls back to Selenium Firefox automatically.

### "GOOGLE_API_KEY_FOR_GEMINI is missing"

Run the wizard:

```bash
python main.py -c
```

Or edit `.env` directly. Get a free key at https://aistudio.google.com.

### "Ollama daemon not reachable at http://localhost:11434"

Start the daemon:

```bash
ollama serve &
ollama pull llama3      # if you haven't already
```

Or point to a remote Ollama:

```bash
export OLLAMA_HOST=http://10.0.0.5:11434
python main.py -i
```

### "ANTHROPIC_API_KEY not set"

```bash
python main.py -c
# (enter your key in the Anthropic section)
```

Or:

```bash
export ANTHROPIC_API_KEY=sk-ant-…
python main.py -i
```

### Cache returning stale data

```bash
python main.py --cache-clear <namespace>
```

Or bypass entirely:

```bash
SCANNUS_CACHE_DISABLE=1 python main.py …
```

### "Module not found: phonenumbers" / "Module not found: pycryptodome"

```bash
pip install -r requirements.txt
```

If you're on Termux and a wheel won't build, try:

```bash
pip install --no-build-isolation phonenumbers
```

### Selenium tests open a browser window

Make sure you're not setting `MOZ_HEADLESS=0`. Headless is the default; if it's been overridden, unset:

```bash
unset MOZ_HEADLESS
```

### "Maigret installation fails"

Maigret pins `aiohttp==3.8.x` which has no aarch64-android wheels. **Use Sherlock instead on Termux**:

```bash
python main.py --username-enum jdoe88 --enum-backend sherlock
```

### Excessive log output

ScannUs is intentionally verbose for transparency. To quiet it:

```bash
python main.py … 2>/dev/null         # suppress warnings
python main.py … 2>&1 | tail -n 20   # last 20 lines only
```

---

## 18. FAQ

**Q: Is ScannUs legal to use?**

A: ScannUs only queries publicly accessible data: search engines, the Internet Archive, public CT logs, public WHOIS records, etc. Whether your *use* is legal depends on your jurisdiction and the purpose. Authorised security testing, journalism, lawful OSINT, and personal account-hygiene audits are typical fair uses. Targeting individuals or systems without authorisation may violate computer-misuse, anti-stalking, or data-protection laws in your country. **You are responsible for compliance.**

**Q: Does ScannUs store my queries or send them to a server?**

A: No. ScannUs runs entirely on your machine. The only outbound traffic is:
- Your direct queries to the search engines you've configured
- HIBP API requests (for breach lookups)
- Wayback Machine requests
- Optional AI provider calls (Gemini/OpenAI/Claude) if you use AI features
- Optional Ollama calls (local, your daemon)

No telemetry, no analytics, no "phone home."

**Q: How much do API costs add up to?**

Rough estimates for moderate use (50 investigations/month):

| Service | Cost |
|---|---|
| Gemini | Free (Free tier has generous limits) |
| OpenAI GPT-4o | ~$2-5/month |
| Anthropic Claude | ~$2-5/month |
| Ollama | $0 (local) |
| HIBP (paid) | $3.50/month flat |
| Google Custom Search | First 100 queries/day free, then $5 per 1000 |
| Brave Search | $3/month for 2000 queries |
| Shodan | $59/month for the basic plan |

You can run ScannUs with **zero paid services** by sticking to DuckDuckGo + free HIBP endpoints + Ollama for AI.

**Q: Will the cache make me miss new results?**

Default TTLs are conservative:
- 24h for SERPs (search results don't drift fast)
- 6h for page content
- 1h for DNS

If you suspect stale data, `--cache-clear <namespace>` and re-run. Wayback snapshots are cached for 30 days because they're immutable by design.

**Q: Can I run ScannUs in a Docker container?**

There's no official Dockerfile yet, but a minimal one works:

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y firefox-esr
RUN wget https://github.com/mozilla/geckodriver/releases/download/v0.34.0/geckodriver-v0.34.0-linux64.tar.gz \
    && tar -xzf geckodriver-v0.34.0-linux64.tar.gz \
    && mv geckodriver /usr/local/bin/
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
CMD ["python", "main.py", "-i"]
```

**Q: How do I add a new search engine?**

Implement a class in `search/engines/` that exposes:

```python
def search(query: str, pages: int, start_page: int, lang: str) -> list[dict]:
    # return [{"title": ..., "link": ..., "description": ...}, ...]
```

Register it in `cli/actions.py:get_search_engine()` and `cli/menus.py:_ENGINE_CHOICES`.

**Q: How do I add a new AI provider?**

Implement a class with `generate(prompt)` + `stream(prompt, render)` in `core/ai_agent.py`. Register it in `cli/menus.py:select_ia_agent()`. The provider must:

1. Yield text chunks from `stream()`
2. Return the joined string from `generate()`

**Q: How do I add a new tool to the AI Query Planner?**

1. Implement the function in the appropriate module (`analysis/`, `search/`, etc.)
2. Add a catalog entry in `core/ai_agent.py:TOOL_CATALOG` with `desc` and `args`
3. Write a `_dispatch_<name>(args, ia_agent)` function that returns `{status, summary, data}`
4. Register it in `core/ai_agent.py:TOOL_DISPATCH`

That's it — the planner will auto-discover it from `TOOL_CATALOG`.

**Q: Can I script ScannUs from Python?**

Yes:

```python
from analysis.hibp import check_account
from analysis.domain_osint import domain_recon
from analysis.advanced_osint import wayback_fetch_snapshot

# Use any module function directly
result = check_account("target@example.com")
recon  = domain_recon("example.com")
snap   = wayback_fetch_snapshot("https://example.com", "2020")
```

All cached calls work transparently — no need to wire up the cache yourself.

---

## 19. Glossary

| Term | Definition |
|---|---|
| **CDX** | Internet Archive's snapshot index API |
| **CSE** | Google's Custom Search Engine product (paid SERP API) |
| **CT log** | Certificate Transparency log — public, append-only registry of issued TLS certs. crt.sh is a frontend. |
| **Deep search** | ScannUs's `--deep` mode: search, then crawl each result URL and extract PII |
| **DKIM** | DomainKeys Identified Mail — email authentication via DNS-published public keys |
| **Dork** | A Google search query using advanced operators (`site:`, `filetype:`, etc.) to find non-obvious content |
| **EIP-55** | Ethereum address mixed-case checksum scheme |
| **HIBP** | Have I Been Pwned — Troy Hunt's breach intelligence database |
| **k-anonymity** | Privacy-preserving lookup: send a hash prefix, match the suffix locally. Used by Pwned Passwords. |
| **OSINT** | Open-Source Intelligence: gathering info from public sources |
| **PEM** | Privacy-Enhanced Mail — text format for cryptographic keys (`-----BEGIN…-----` blocks) |
| **PII** | Personally Identifiable Information |
| **Plan** | A multi-step investigation strategy produced by the AI Query Planner |
| **PWA / SPA** | Single-Page Application — JS-rendered site that static HTTP can't see |
| **ReAct** | Reasoning + Acting: an LLM agent pattern that interleaves planning, action, and observation |
| **SAN** | Subject Alternative Name — additional hostnames covered by a TLS cert |
| **SPF / DMARC** | Email authentication via DNS TXT records |
| **TUI** | Text User Interface (the interactive menu) |
| **WAL** | Write-Ahead Log — SQLite journal mode that enables concurrent reads |
| **Wayback** | The Internet Archive's snapshot service |

---

<div align="center">

**Happy investigating.**

For bug reports and feature requests, see the [GitHub repository](https://github.com/kahz12/scannus/issues).

</div>
