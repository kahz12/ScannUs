# ScannUs — Advanced OSINT & Web Analysis Tool

**ScannUs** is a modular command-line OSINT framework for investigations, web analysis, and automated intelligence gathering. It integrates multiple search engines (Google, DuckDuckGo, Brave), AI assistants (Gemini, OpenAI/GPT-4o), and an interactive Rich TUI.

---

## 🚀 Features

### 🔍 Search & Intelligence
- **Multi-Engine Search** — Google Custom Search, DuckDuckGo (anonymous), Brave Search with in-session **LRU cache** (no duplicate API calls)
- **Guided Search** — compose queries from name + username + email + phone interactively
- **AI Dork Generation** — describe what you want in plain language; the LLM generates precise Google Dorks
- **Reverse Image Search** — Yandex visual search via headless Selenium

### 🤖 AI Analysis (Streaming)
- **Real-time streaming** output for both OpenAI and Gemini models
- **Content Summarization** — AI-powered summary of any webpage
- **Deep OSINT Analysis** — extract entities, leads, and key topics from page content
- **Long-text chunking** — texts > 12 k chars are processed in overlapping chunks and merged, instead of being truncated

### 🕵️ Evidence Collection
- **Deep Scraping (Selenium)** — render JavaScript, simulate scrolling, extract hidden content from SPAs
- **Wayback Machine** — check historical page snapshots
- **Email & Phone Extraction** — international formats, obfuscation decoding (`[at]`, `(dot)`), HTML `mailto`/`tel` attributes, false-positive filtering
- **File Downloads** — batch-download PDFs, DOCXs, and other file types found in results

### 📹 Media Downloader (Three-tier Video Strategy)
| Tier | Method | Covers |
|------|--------|--------|
| 1st | **yt-dlp** | 1000+ sites — YouTube, Vimeo, TikTok, Instagram, Twitter, HLS/DASH streams |
| 2nd | **Selenium click-play** | Custom/unknown players — clicks play, waits 2 s, reads populated `<video src>` |
| 3rd | **Static HTML** | Direct-linked `<video src="…">` without JavaScript |

- Concurrent downloads via `ThreadPoolExecutor`
- MIME-type-aware file organization (`images/`, `videos/`, `audio/`)
- 5 KB minimum size filter (skips tracking pixels)
- Retry with exponential backoff (3 attempts)
- Output as structured ZIP archive

### 🔬 Site Analysis
- **Technology Stack Detection** — WebTech fingerprinting with Category column (CMS, Framework, CDN, Server…)
- **Entity Relationship Graph** — AI extracts entities and renders an interactive Pyvis HTML graph
- **Metadata Extraction** — EXIF data from downloaded images

### 💾 Case Management
- Save / load investigation sessions to local **SQLite** database
- **Overwrite prompt** when a case name already exists
- Update and delete cases

### 📊 Export
- **Excel** (`.xlsx`) — styled header, alternating row colors, hyperlinks, auto-fit columns
- **CSV**, **JSON**, **HTML** reports

### 🎨 TUI & UX
- Fully themed **Rich** terminal UI (panels, tables, spinners, gradient banner)
- **Paginated results** — 10 per page with `n` next · `p` prev · `j <N>` jump · `all` full list
- **AI response streaming** rendered live in terminal
- `console.input()` everywhere — Rich markup in prompts renders correctly

---

## 🛠️ Installation

```bash
# 1. Clone
git clone https://github.com/kahz12/scannus.git
cd scannus

# 2. Virtual environment
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 3. Dependencies (includes yt-dlp, rich, selenium, webtech, openpyxl…)
pip install -r requirements.txt
```

> **Firefox** must be installed for Selenium-based features (Deep Scraping, Screenshots, Reverse Image Search, Selenium video extraction).

---

## ⚙️ Configuration

```bash
# Interactive wizard — sets API keys in .env
python main.py -c
```

Copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
```

| Variable | Service | Required for |
|----------|---------|-------------|
| `API_KEY_GOOGLE` | Google Cloud | Google Search |
| `SEARCH_ENGINE_ID` | Programmable Search Engine | Google Search |
| `GOOGLE_API_KEY_FOR_GEMINI` | Google AI Studio | Gemini AI features |
| `BRAVE_API_KEY` | Brave Search API | Brave engine |
| `OPENAI_API_KEY` | OpenAI Platform | GPT-4o AI features |

---

## 📖 Usage

### Interactive TUI (recommended)
```bash
python main.py        # full interactive menu
python main.py -i     # same, explicit flag
```

### Command Line

```bash
# Basic search (DuckDuckGo by default)
python main.py -q "site:linkedin.com \"project manager\""

# Multi-engine with pagination
python main.py -q "OSINT tools" --engine brave --pages 2

# AI-generated Dork
python main.py -gd "Find PDF contracts of government tech projects"

# Guided multi-field search
python main.py -n "John Doe" -u "jdoe88" --engine google

# Media download (videos auto-use yt-dlp)
python main.py --media-scrape "https://example.com/gallery"

# Deep extraction + Excel export
python main.py -q "target@corp.com" --deep --excel results.xlsx

# Load a saved case
python main.py --load-case
```

### Result navigation (interactive menu)

| Command | Action |
|---------|--------|
| `<ID>` | Analyse result URL |
| `n` | Next page |
| `p` | Previous page |
| `j 3` | Jump to page 3 |
| `all` | Show all results |
| `media` | Download media from selected IDs |
| `save` | Save case to database |
| `excel` | Export to Excel |
| `exit` | Return to main menu |

---

## 🏗️ Project Structure

```
ScannUs/
├── main.py                  # Entry point
├── cli/
│   ├── ui.py                # Rich theme, console helpers, make_table()
│   ├── menus.py             # Interactive TUI menus (paginated)
│   ├── actions.py           # CLI action handlers
│   └── parser.py            # Argument parser + styled help
├── core/
│   ├── config.py            # Directory init, API credential wizard
│   ├── ai_agent.py          # Streaming AI (OpenAI + Gemini)
│   ├── case_manager.py      # Save/load cases with overwrite prompt
│   └── database.py          # SQLite DAO (save, update, delete)
├── search/
│   ├── smart_search.py      # Email/phone extraction + obfuscation decoder
│   ├── reverse_image.py     # Yandex reverse image search
│   └── engines/
│       ├── googlesearch.py  # Google Custom Search API
│       ├── duckduckgosearch.py
│       ├── bravesearch.py
│       └── cache.py         # Session-scoped LRU cache (128 entries)
├── analysis/
│   ├── web_analyzer.py      # Text extraction + AI analysis (chunked)
│   ├── tech_scanner.py      # WebTech fingerprinting + category column
│   └── advanced_osint.py    # Selenium deep scraping + screenshots
└── utils/
    ├── media_downloader.py  # 3-tier video: yt-dlp → Selenium → static
    ├── results_parse.py     # Results table + Excel export
    └── file_download.py     # Batch file downloader
```

---

## ⚠️ Disclaimer

This tool is intended for **educational and research purposes only**. The user is responsible for ensuring that their activities comply with all applicable laws and regulations. Do not use this tool for unauthorized scanning or illegal activities.

---
Developed with ❤️ by Ale
