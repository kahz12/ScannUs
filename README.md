<div align="center">

```
 ____                        _   _
/ ___|  ___ __ _ _ __  _ __ | | | |___
\___ \ / __/ _` | '_ \| '_ \| | | / __|
 ___) | (_| (_| | | | | | | | |_| \__ \
|____/ \___\__,_|_| |_|_| |_|\___/|___/
```

**Advanced OSINT & Web Intelligence Framework**

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue?style=flat-square&logo=python)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Active-brightgreen?style=flat-square)]()

</div>

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Features](#features)
4. [Prerequisites](#prerequisites)
5. [Installation](#installation)
6. [Configuration](#configuration)
7. [Usage](#usage)
   - [Interactive TUI](#interactive-tui)
   - [Command-Line Interface](#command-line-interface)
   - [Result Navigation](#result-navigation)
8. [Project Structure](#project-structure)
9. [Database Schema](#database-schema)
10. [Output Directory Layout](#output-directory-layout)
11. [Disclaimer](#disclaimer)

---

## Overview

**ScannUs** is a modular, open-source **OSINT (Open Source Intelligence) framework** built for investigators, security researchers, and analysts who need to automate intelligence gathering from public web sources.

It unifies multiple search engines, AI assistants, and specialized extraction tools under a single interactive terminal interface, allowing the user to go from a raw query to a structured investigation — complete with exported evidence, entity graphs, and case management — without leaving the terminal.

### What ScannUs solves

| Problem | ScannUs solution |
|---|---|
| Manually querying multiple search engines | Unified multi-engine search with session-level LRU cache |
| Writing Google Dorks by hand | Plain-language AI dork generation (Gemini / GPT-4o) |
| Extracting emails/phones from pages | Regex + obfuscation decoder covering `[at]`, `(dot)`, HTML entities |
| Downloading media from diverse platforms | Three-tier strategy: yt-dlp → Selenium → static HTML |
| Keeping track of multiple investigations | SQLite case management with save / load / update / delete |
| Producing shareable evidence | Excel, CSV, JSON, and HTML export with one command |

---

## Architecture

ScannUs follows a **layered, modular architecture**. Each layer has a single responsibility and communicates through well-defined interfaces.

```
┌──────────────────────────────────────────────────────────────────────┐
│                          Entry Point                                 │
│                           main.py                                    │
└────────────────────────────┬─────────────────────────────────────────┘
                             │
          ┌──────────────────▼──────────────────┐
          │               CLI Layer              │
          │  parser.py  │  menus.py  │ actions.py│
          │              ui.py                   │
          └──────────────────┬──────────────────-┘
                             │
     ┌───────────────────────▼────────────────────────┐
     │                   Core Layer                    │
     │  config.py │ ai_agent.py │ case_manager.py      │
     │  database.py │ state.py                         │
     └──────┬───────────────┬──────────────────────────┘
            │               │
   ┌────────▼──────┐  ┌─────▼──────────────────────┐
   │  Search Layer │  │       Analysis Layer        │
   │  engines/     │  │  web_analyzer.py            │
   │  smart_search │  │  tech_scanner.py            │
   │  reverse_image│  │  advanced_osint.py          │
   └───────────────┘  └────────────────┬────────────┘
                                       │
                          ┌────────────▼────────────┐
                          │       Utils Layer        │
                          │  media_downloader.py     │
                          │  results_parse.py        │
                          │  file_download.py        │
                          └─────────────────────────┘
```

### Design patterns used

| Pattern | Location | Purpose |
|---------|----------|---------|
| Strategy | `core/ai_agent.py` | Switchable AI backends (Gemini / OpenAI) |
| Factory | `search/engines/` | `_get_search_engine()` instantiates correct engine at runtime |
| DAO | `core/database.py` | Decoupled SQLite access layer |
| Singleton | `search/engines/cache.py` | Session-scoped LRU cache (128 entries) |
| State | `core/state.py` | Global runtime state shared across modules |

---

## Features

### Search & Intelligence

- **Multi-Engine Search** — Google Custom Search API, DuckDuckGo (anonymous HTML scraping), and Brave Search API, all behind a session-scoped **LRU cache** (128 entries) that eliminates duplicate API calls within the same session.
- **Paginated Results** — results displayed 10 per page with keyboard navigation (`n`, `p`, `j <N>`, `all`).
- **Guided Search** — interactive prompt collects name, username, email, and phone, then assembles an optimised compound query.
- **AI Dork Generation** — describe your target in natural language; the AI produces precise Google Dork syntax ready to execute.
- **Reverse Image Search** — headless Selenium drives Yandex Images and returns parsed results.

### AI Analysis (Streaming)

- **Dual AI Backends** — Google Gemini and OpenAI GPT-4o, selectable at runtime; responses stream token-by-token to the terminal.
- **Webpage Summarisation** — AI reads extracted plain text and produces a concise summary.
- **Deep OSINT Analysis** — the AI identifies entities, relationships, leads, and key intelligence points from page content.
- **Long-text Chunking** — texts exceeding 12 KB are split into overlapping 12 KB chunks (500-character overlap) and the AI processes each chunk; results are merged into a single coherent output rather than truncating content.
- **Entity Relationship Graph** — extracted entities are fed to Pyvis to produce an interactive HTML graph saved in `outputs/graphs/`.

### Evidence Collection

- **Deep Web Scraping (Selenium)** — headless Firefox renders JavaScript, simulates scrolling, and extracts hidden content from Single-Page Applications that static HTTP requests cannot reach.
- **Screenshot Capture** — saves full-page PNG screenshots via Selenium to `outputs/screenshots/`.
- **Wayback Machine Lookup** — queries the Internet Archive API for historical snapshots of any URL.
- **Email & Phone Extraction** — international phone number formats; email obfuscation decoding (`[at]`, `(dot)`, `&#64;`, spaced variants), HTML `mailto:`/`tel:` attribute parsing, and false-positive filtering that excludes `noreply@*`, bots, and test domains.
- **File Downloads** — batch-downloads PDFs, DOCXs, and other file types discovered in results; extracts EXIF metadata from images and PDF document properties.

### Media Downloader — Three-Tier Strategy

The media downloader attempts the following methods in order, falling back to the next tier only on failure:

| Tier | Method | Coverage |
|------|--------|----------|
| 1st | **yt-dlp** | 1 000+ platforms — YouTube, Vimeo, TikTok, Instagram, Twitter/X, Twitch, HLS/DASH streams |
| 2nd | **Selenium click-play** | Custom/proprietary players — clicks the play button, waits 2 s for the `src` to populate, then reads `<video src>` |
| 3rd | **Static HTML** | Direct-linked `<video src="…">` elements that do not require JavaScript |

Additional download features:
- Concurrent downloads via `ThreadPoolExecutor`
- MIME-type-aware organisation into `images/`, `videos/`, `audio/` sub-directories
- 5 KB minimum size filter (eliminates tracking pixels and empty responses)
- Retry with exponential backoff (3 attempts)
- Final output packaged as a structured ZIP archive

### Site Analysis

- **Technology Stack Detection** — WebTech fingerprinting identifies CMS, framework, CDN, web server, programming language, and analytics tools.
- **Metadata Extraction** — EXIF data extracted from downloaded images; document properties from PDFs.

### Case Management

- Save the current investigation (query, engine, results) to a local **SQLite** database under a named case.
- **Overwrite protection** — prompts before replacing an existing case name.
- Load, update, and delete cases from the interactive menu or CLI.

### Export Formats

| Format | File | Details |
|--------|------|---------|
| Excel | `.xlsx` | Styled header row, alternating row colours, clickable hyperlinks, auto-fit column widths |
| CSV | `.csv` | Plain comma-separated for spreadsheet import |
| JSON | `.json` | Structured object array for programmatic processing |
| HTML | `.html` | Self-contained report for sharing |

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Python 3.8+ | Tested on 3.10 and 3.12 |
| Firefox | Required for Selenium features: Deep Scraping, Screenshots, Reverse Image Search, Selenium video extraction |
| pip | For dependency installation |
| API keys | At least one search engine key; AI features require Gemini or OpenAI key |

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/kahz12/scannus.git
cd scannus

# 2. Create an isolated virtual environment
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 3. Install all dependencies
pip install -r requirements.txt
```

> The `requirements.txt` includes: `rich`, `selenium`, `webtech`, `yt-dlp`, `openpyxl`, `pyvis`, `beautifulsoup4`, `requests`, `python-dotenv`, `PyPDF2`, `exifread`, and more.

---

## Configuration

ScannUs reads API credentials from a `.env` file in the project root. The quickest way to set it up is the built-in interactive wizard:

```bash
python main.py -c
```

This prompts for each key and writes them to `.env` automatically. Alternatively, copy the provided template and fill in values manually:

```bash
cp .env.example .env
```

### Environment variables

| Variable | Service | Required for |
|---|---|---|
| `API_KEY_GOOGLE` | Google Cloud Console | Google Custom Search |
| `SEARCH_ENGINE_ID` | Programmable Search Engine | Google Custom Search |
| `GOOGLE_API_KEY_FOR_GEMINI` | Google AI Studio | All Gemini AI features |
| `BRAVE_API_KEY` | Brave Search API | Brave Search engine |
| `OPENAI_API_KEY` | OpenAI Platform | GPT-4o AI features |

### Obtaining API keys

- **Google Custom Search**: Create a project in [Google Cloud Console](https://console.cloud.google.com/), enable the *Custom Search API*, generate an API key, and create a Programmable Search Engine at [cse.google.com](https://cse.google.com/) to get the `SEARCH_ENGINE_ID`.
- **Gemini**: Generate a free key at [Google AI Studio](https://aistudio.google.com/).
- **Brave Search**: Register at [Brave Search API](https://api.search.brave.com/).
- **OpenAI**: Create a key at [platform.openai.com](https://platform.openai.com/).

> DuckDuckGo does **not** require an API key and is available by default.

---

## Usage

### Interactive TUI

Launch the full interactive menu (recommended for investigations):

```bash
python main.py        # default interactive mode
python main.py -i     # explicit flag, identical behaviour
```

**Main menu options:**

```
1. Basic Search (DuckDuckGo)
2. Google Custom Search
3. Brave Search
4. Generate Google Dork with AI
5. Guided Search  (name + username + email + phone)
6. Reverse Image Search
7. Configure API Keys
8. Load Saved Case
```

**URL analysis sub-menu** (after selecting a result by ID):

```
1. Summarise content          (AI)
2. Extract PII                (email / phone regex)
3. Scan web technologies      (WebTech fingerprinting)
4. Download file
5. Download media             (images / video / audio)
6. Capture screenshot         (Selenium)
7. Wayback Machine history
8. Deep AI analysis           (OSINT mode)
9. Extract entities & build graph (Pyvis)
```

---

### Command-Line Interface

ScannUs exposes all features via CLI flags for scripting and automation.

#### Query options

```bash
python main.py -q "site:linkedin.com \"project manager\" \"New York\""
python main.py -q "OSINT tools" --engine brave --pages 2
python main.py -n "John Doe" -u "jdoe88" -e "john@corp.com" --engine google
python main.py -gd "Find exposed admin panels on government domains"
```

#### Analysis & extraction

```bash
# Deep extraction — crawl result URLs and extract PII
python main.py -q "target@corp.com" --deep

# Download media from a URL (three-tier strategy)
python main.py --media-scrape "https://example.com/gallery"

# Reverse image search
python main.py --reverse
```

#### Export

```bash
python main.py -q "query" --excel results.xlsx
python main.py -q "query" --csv results.csv
python main.py -q "query" --json results.json
python main.py -q "query" --html report.html
```

#### Case management

```bash
python main.py --load-case          # list and load a saved case
python main.py -c                   # configure API credentials
```

#### Full flag reference

| Flag | Short | Description |
|------|-------|-------------|
| `--query TEXT` | `-q` | Direct search query or dork |
| `--nombre TEXT` | `-n` | Person name (guided search) |
| `--usuario TEXT` | `-u` | Username |
| `--email TEXT` | `-e` | Email address |
| `--telefono TEXT` | `-t` | Phone number |
| `--buscar TEXT` | `-b` | Additional search term |
| `--engine ENGINE` | | `google` / `duckduckgo` / `brave` (default: `duckduckgo`) |
| `--pages N` | | Number of result pages to fetch (default: 1) |
| `--start-page N` | | First page number (default: 1) |
| `--lang LANG` | | Language filter, e.g. `lang_es`, `lang_en` |
| `--interactive` | `-i` | Launch interactive TUI mode |
| `--deep` | | Deep extraction: crawl result URLs and extract PII |
| `--google-dorks DESC` | `-gd` | Generate a Google Dork from a natural-language description |
| `--reverse` | | Launch reverse image search |
| `--media-scrape URL` | | Download media (images / video / audio) from URL |
| `--excel FILE` | | Export results to Excel |
| `--csv FILE` | | Export results to CSV |
| `--json FILE` | | Export results to JSON |
| `--html FILE` | | Export results to HTML |
| `--download TYPES` | | Download files found in results: `pdf`, `docx`, `txt`, `all` |
| `--metadata` | | Extract PDF and EXIF metadata from downloaded files |
| `--load-case` | | Load a saved investigation from the database |
| `--configure` | `-c` | Launch the API key configuration wizard |

---

### Result Navigation

Once search results are displayed, the interactive prompt accepts these commands:

| Input | Action |
|-------|--------|
| `<ID>` | Open analysis sub-menu for result number `<ID>` |
| `n` | Next page |
| `p` | Previous page |
| `j <N>` | Jump to page `<N>` |
| `all` | Display all results on a single page |
| `media <ID,…>` | Download media from selected result IDs |
| `save` | Save the current session as a named case |
| `excel` | Export current results to Excel |
| `exit` | Return to the main menu |

---

## Project Structure

```
ScannUs/
├── main.py                        # Entry point — CLI dispatch & initialisation
├── requirements.txt               # Python dependencies
├── .env.example                   # API credentials template
│
├── cli/
│   ├── ui.py                      # Rich theme, console helpers, make_table()
│   ├── parser.py                  # Argument parser and styled help screen
│   ├── menus.py                   # Interactive TUI menus with pagination
│   └── actions.py                 # CLI action handlers (search, deep extraction)
│
├── core/
│   ├── config.py                  # Output directory init, API wizard
│   ├── ai_agent.py                # Streaming AI — Strategy pattern (Gemini + OpenAI)
│   ├── case_manager.py            # Save / load / update / delete cases
│   ├── database.py                # SQLite DAO
│   └── state.py                   # Global runtime state
│
├── search/
│   ├── smart_search.py            # Email / phone extraction + obfuscation decoder
│   ├── reverse_image.py           # Yandex reverse image search via Selenium
│   └── engines/
│       ├── googlesearch.py        # Google Custom Search API client
│       ├── duckduckgosearch.py    # DuckDuckGo HTML scraper
│       ├── bravesearch.py         # Brave Search API client
│       └── cache.py               # Session-scoped LRU cache (128 entries)
│
├── analysis/
│   ├── web_analyzer.py            # Text extraction, chunking, AI summarisation
│   ├── tech_scanner.py            # WebTech fingerprinting with category column
│   └── advanced_osint.py          # Selenium deep scraping, screenshots, Wayback Machine
│
└── utils/
    ├── media_downloader.py        # Three-tier video/image downloader (yt-dlp → Selenium → static)
    ├── results_parse.py           # Excel / CSV / JSON / HTML export
    └── file_download.py           # Batch file downloader + metadata extraction
```

---

## Database Schema

Cases and results are persisted in a local SQLite database at `outputs/cases/cases.db`.

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

---

## Output Directory Layout

All generated files are written inside the `outputs/` directory, which is created automatically on first run.

```
outputs/
├── cases/
│   └── cases.db           # SQLite investigation database
├── downloads/
│   ├── images/            # Downloaded images (MIME-sorted)
│   ├── videos/            # Downloaded video files
│   ├── audio/             # Downloaded audio files
│   ├── docs/              # PDFs, DOCXs, and other documents
│   └── other/             # Files with unrecognised MIME types
├── media/                 # ZIP archives from --media-scrape
├── reports/               # Excel / CSV / JSON / HTML exports
├── screenshots/           # Selenium full-page screenshots (PNG)
└── graphs/                # Pyvis entity relationship graphs (HTML)
```

---

## Disclaimer

ScannUs is intended strictly for **educational purposes, authorised security research, and lawful open-source intelligence gathering**. The user assumes full responsibility for ensuring that all activities performed with this tool comply with applicable local, national, and international laws and regulations.

**Do not use ScannUs against systems, accounts, or data for which you do not have explicit authorisation.**

---

<div align="center">
Developed by Ale
</div>
