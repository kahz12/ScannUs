# ScannUs - Advanced OSINT & Web Analysis Tool

**ScannUs** is a powerful, modular command-line tool designed for **OSINT (Open Source Intelligence)** investigations, web technology analysis, and automated information gathering. It integrates multiple search engines (Google, DuckDuckGo, Brave) and leverages modern Artificial Intelligence (Gemini, OpenAI) to assist researchers in generating precise Google Dorks and summarizing content.

## 🚀 Key Features

- **Multi-Engine Search**: Perform searches using **Google Custom Search**, **DuckDuckGo** (anonymous), or **Brave Search**.
- **AI-Powered Assistance**:
    - **Dork Generation**: Describe what you are looking for in plain language, and the AI (Gemini or GPT-4o) will generate advanced Google Dorks for you.
    - **Content Summarization**: Automatically summarize the content of analyzed webpages.
- **Evidence Collection & Analysis**:
    - **Deep Scraping (Selenium)**: Render JavaScript, simulate deep scrolling and extract hidden textual evidence from Single Page Applications.
    - **Wayback Machine Integration**: Automatically checks the historical archives for analyzed links.
    - **Media Scraping**: Download images and videos from a target URL straight into a ZIP file.
    - **Technology Stack Detection**: Identify frameworks, CMS, and libraries used by a website.
    - **Information & Metadata Extraction**: Automatically extract emails, phone numbers, and fetch local metadata including internal picture EXIFs.
- **Visualization Tools**:
    - **Relationship Graphs (Pyvis)**: Map AI-extracted entities (persons, locations, IPs) into interactive HTML node graphs.
- **Session Management (Outputs)**:
    - Clean and centralized hierarchy via the `outputs/` directory, properly sorting databases (`cases/`), raw files (`downloads/`), exportables (`reports/`), bundled stuff (`media/`), visual evidence (`screenshots/`) and `graphs/`.
- **Case Management**: Save your search sessions and results into JSON "cases" to reload and analyze later.
- **Reverse Image Search**: Perform reverse image searches to find the source of an image.
- **File Downloads**: Automatically download files (PDF, DOCX, etc.) discovered during searches.

## 🛠️ Installation

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/kahz12/scannus.git
    cd scannus
    ```

2.  **Set up a Virtual Environment (Recommended)**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # On Windows use: venv\Scripts\activate
    ```

3.  **Install Dependencies**:
    The project relies on libraries such as `google-genai`, `requests`, `beautifulsoup4`, `rich`, `selenium`, `exifread`, `pyvis` and `webtech`.
    Note that **Firefox** must be installed in order to successfully run the Deep Scraping and Visual Screenshot engines.
    ```bash
    pip install -r requirements.txt
    ```

## ⚙️ Configuration

ScannUs uses environment variables to manage API keys. You can configure them interactively.

1.  **Run the configuration wizard**:
    ```bash
    python main.py -c
    ```
2.  **Enter your API Keys**:
    -   **Google Custom Search**: Required for Google searches (`API_KEY_GOOGLE` and `SEARCH_ENGINE_ID`).
    -   **Google Gemini**: Required for AI features (`GOOGLE_API_KEY_FOR_GEMINI`).
    -   **Brave Search**: Required for Brave engine (`BRAVE_API_KEY`).
    -   **OpenAI**: Optional alternative for AI (`OPENAI_API_KEY`).

The keys will be saved to a `.env` file in the project root.

## 📖 Usage Examples

You can run ScannUs in **Interactive Mode** or using **Command Line Arguments**.

### 1. Interactive Mode (Menu)
Simply run the script without arguments to see the main menu:
```bash
python main.py
```

### 2. Quick Command Line Searches

-   **Basic Search (DuckDuckGo by default)**:
    ```bash
    python main.py -q "site:linkedin.com \"project manager\""
    ```

-   **Search using Brave Engine**:
    ```bash
    python main.py -q "OSINT resources" --engine brave
    ```

-   **Generate a Dork with AI**:
    ```bash
    python main.py -gd "Find PDF documents about cyber security in government sites"
    ```

-   **Guided Search for a Person**:
    ```bash
    python main.py -n "John Doe" -u "johndoe123"
    ```

-   **Download Media from a URL**:
    ```bash
    python main.py --media-scrape "https://example.com/gallery"
    ```

### Command Line Arguments

| Argument | Description |
| :--- | :--- |
| `-h`, `--help` | Show the help message and exit. |
| `-q`, `--query` | Specify the search query or dork. |
| `-i`, `--interactive` | Enable interactive mode for analyzing results. |
| `-c`, `--configure` | Configure API keys in `.env`. |
| `--engine` | Select search engine: `google`, `duckduckgo` (default), `brave`. |
| `-gd`, `--google-dorks` | Generate a Google Dork using AI from a description. |
| `--media-scrape` | Download all media from a URL to a ZIP file. |
| `--json`, `--csv`, `--html` | Export results to the specified format. |

## ⚠️ Disclaimer
This tool is intended for **educational and research purposes only**. The user is responsible for ensuring that their activities comply with all applicable laws and regulations. Do not use this tool for unauthorized scanning or illegal activities.

---
Developed with ❤️ by Ale
---
