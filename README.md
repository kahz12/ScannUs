# ScannUs - Herramienta Avanzada de OSINT y Análisis Web

**ScannUs** es una poderosa herramienta modular de línea de comandos diseñada para investigaciones **OSINT (Inteligencia de Fuentes Abiertas)**, análisis de tecnología web y recopilación automatizada de información. Integra múltiples motores de búsqueda (Google, DuckDuckGo, Brave) y aprovecha la Inteligencia Artificial moderna (Gemini, OpenAI) para ayudar a los investigadores a generar Google Dorks precisos y resumir contenido.

## 🚀 Características Principales

- **Búsqueda Multi-Motor**: Realiza búsquedas usando **Google Custom Search**, **DuckDuckGo** (anónimo) o **Brave Search**.
- **Asistencia Potenciada por IA**:
    - **Generación de Dorks**: Describe lo que buscas en lenguaje sencillo y la IA (Gemini o GPT-4o) generará Google Dorks avanzados para ti.
    - **Resumen de Contenido**: Resumen automático del contenido de las páginas web analizadas.
- **Scraping y Análisis Avanzado**:
    - **Scraping de Medios**: Descarga todas las imágenes y videos de una URL objetivo en un archivo ZIP.
    - **Detección de Stack Tecnológico**: Identifica frameworks, CMS y librerías utilizadas por un sitio web (potenciado por `webtech`).
    - **Extracción de Información**: Extrae automáticamente correos electrónicos, números de teléfono y enlaces de redes sociales de las páginas.
- **Gestión de Casos**: Guarda tus sesiones de búsqueda y resultados en "casos" JSON para recargarlos y analizarlos más tarde.
- **Búsqueda Inversa de Imágenes**: Realiza búsquedas inversas para encontrar la fuente de una imagen.
- **Descarga de Archivos**: Descarga automáticamente archivos (PDF, DOCX, etc.) descubiertos durante las búsquedas.

## 🛠️ Instalación

1.  **Clonar el repositorio**:
    ```bash
    git clone https://github.com/kahz12/scannus.git
    cd scannus
    ```

2.  **Configurar un Entorno Virtual (Recomendado)**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # En Windows usa: venv\Scripts\activate
    ```

3.  **Instalar Dependencias**:
    El proyecto depende de varias librerias de Python incluyendo `google-genai`, `requests`, `beautifulsoup4`, `rich` y `webtech`.
    ```bash
    pip install -r requirements.txt
    ```

## ⚙️ Configuración

ScannUs utiliza variables de entorno para gestionar las claves API. Puedes configurarlas interactivamente.

1.  **Ejecutar el asistente de configuración**:
    ```bash
    python main.py -c
    ```
2.  **Ingresa tus Claves API**:
    -   **Google Custom Search**: Requerido para búsquedas de Google (`API_KEY_GOOGLE` y `SEARCH_ENGINE_ID`).
    -   **Google Gemini**: Requerido para funciones de IA (`GOOGLE_API_KEY_FOR_GEMINI`).
    -   **Brave Search**: Requerido para el motor Brave (`BRAVE_API_KEY`).
    -   **OpenAI**: Alternativa opcional para IA (`OPENAI_API_KEY`).

Las claves se guardarán en un archivo `.env` en la raíz del proyecto.

## 📖 Ejemplos de Uso

Puedes ejecutar ScannUs en **Modo Interactivo** o usando **Argumentos de Línea de Comandos**.

### 1. Modo Interactivo (Menú)
Simplemente ejecuta el script sin argumentos para ver el menú principal:
```bash
python main.py
```

### 2. Búsquedas Rápidas por Línea de Comandos

-   **Búsqueda Básica (DuckDuckGo por defecto)**:
    ```bash
    python main.py -q "site:linkedin.com \"project manager\""
    ```

-   **Búsqueda usando el Motor Brave**:
    ```bash
    python main.py -q "Recursos OSINT" --engine brave
    ```

-   **Generar un Dork con IA**:
    ```bash
    python main.py -gd "Encontrar documentos PDF sobre ciberseguridad en sitios gubernamentales"
    ```

-   **Búsqueda Guiada para una Persona**:
    ```bash
    python main.py -n "Juan Perez" -u "jperez123"
    ```

-   **Descargar Medios de una URL**:
    ```bash
    python main.py --media-scrape "https://ejemplo.com/galeria"
    ```

### Argumentos de Línea de Comandos

| Argumento | Descripción |
| :--- | :--- |
| `-h`, `--help` | Muestra el mensaje de ayuda y sale. |
| `-q`, `--query` | Especifica la consulta de búsqueda o dork. |
| `-i`, `--interactive` | Activa el modo interactivo para analizar resultados. |
| `-c`, `--configure` | Configura las claves API en `.env`. |
| `--engine` | Selecciona el motor de búsqueda: `google`, `duckduckgo` (defecto), `brave`. |
| `-gd`, `--google-dorks` | Genera un Google Dork usando IA a partir de una descripción. |
| `--media-scrape` | Descarga todos los medios de una URL a un archivo ZIP. |
| `--json`, `--csv`, `--html` | Exporta los resultados al formato especificado. |

## ⚠️ Descargo de Responsabilidad
Esta herramienta está destinada únicamente para **fines educativos y de investigación**. El usuario es responsable de asegurar que sus actividades cumplan con todas las leyes y regulaciones aplicables. No utilice esta herramienta para escaneos no autorizados o actividades ilegales.

---
Desarrollado con ❤️ por Ale
---

# ScannUs - Advanced OSINT & Web Analysis Tool

**ScannUs** is a powerful, modular command-line tool designed for **OSINT (Open Source Intelligence)** investigations, web technology analysis, and automated information gathering. It integrates multiple search engines (Google, DuckDuckGo, Brave) and leverages modern Artificial Intelligence (Gemini, OpenAI) to assist researchers in generating precise Google Dorks and summarizing content.

## 🚀 Key Features

- **Multi-Engine Search**: Perform searches using **Google Custom Search**, **DuckDuckGo** (anonymous), or **Brave Search**.
- **AI-Powered Assistance**:
    - **Dork Generation**: Describe what you are looking for in plain language, and the AI (Gemini or GPT-4o) will generate advanced Google Dorks for you.
    - **Content Summarization**: Automatically summarize the content of analyzed webpages.
- **Advanced Scraping & Analysis**:
    - **Media Scraping**: Download all images and videos from a target URL into a ZIP file.
    - **Technology Stack Detection**:Identify frameworks, CMS, and libraries used by a website (powered by `webtech`).
    - **Information Extraction**: Automatically extract emails, phone numbers, and social media links from pages.
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
    The project relies on several Python libraries including `google-genai`, `requests`, `beautifulsoup4`, `rich`, and `webtech`.
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
