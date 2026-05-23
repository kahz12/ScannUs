# ScannUs — Guía de Usuario

Recorrido exhaustivo de cada función, flujo de trabajo y opción de configuración de ScannUs.

---

## Tabla de Contenidos

1. [Primeros Pasos](#1-primeros-pasos)
   - 1.1 [Instalación](#11-instalación)
   - 1.2 [Primera Ejecución](#12-primera-ejecución)
   - 1.3 [Asistente de Configuración](#13-asistente-de-configuración)
2. [Conceptos Centrales](#2-conceptos-centrales)
   - 2.1 [Modo Interactivo vs Modo CLI](#21-modo-interactivo-vs-modo-cli)
   - 2.2 [Casos](#22-casos)
   - 2.3 [La Caché Persistente](#23-la-caché-persistente)
   - 2.4 [Proveedores de IA](#24-proveedores-de-ia)
3. [Búsqueda](#3-búsqueda)
   - 3.1 [Búsqueda Directa](#31-búsqueda-directa)
   - 3.2 [Búsqueda Guiada](#32-búsqueda-guiada)
   - 3.3 [Comparativa de Motores](#33-comparativa-de-motores)
   - 3.4 [Paginación e Idiomas](#34-paginación-e-idiomas)
4. [Funciones de IA](#4-funciones-de-ia)
   - 4.1 [Elección de Proveedor](#41-elección-de-proveedor)
   - 4.2 [Generador de Dorks con IA](#42-generador-de-dorks-con-ia)
   - 4.3 [Planificador de Consultas con IA (ReAct)](#43-planificador-de-consultas-con-ia-react)
   - 4.4 [El Catálogo de Herramientas](#44-el-catálogo-de-herramientas)
5. [Análisis por URL](#5-análisis-por-url)
   - 5.1 [Resumir Contenido](#51-resumir-contenido)
   - 5.2 [Extraer PII](#52-extraer-pii)
   - 5.3 [Escaneo de Tecnologías Web](#53-escaneo-de-tecnologías-web)
   - 5.4 [Descargar Archivo](#54-descargar-archivo)
   - 5.5 [Descargar Medios](#55-descargar-medios)
   - 5.6 [Capturar Pantalla](#56-capturar-pantalla)
   - 5.7 [Wayback Machine](#57-wayback-machine)
   - 5.8 [Análisis Profundo con IA](#58-análisis-profundo-con-ia)
   - 5.9 [Grafo de Relaciones entre Entidades](#59-grafo-de-relaciones-entre-entidades)
   - 5.10 [Scraping Profundo (Renderizado JS)](#510-scraping-profundo-renderizado-js)
6. [Búsqueda Inversa de Imágenes](#6-búsqueda-inversa-de-imágenes)
7. [Enumeración de Usuarios](#7-enumeración-de-usuarios)
8. [OSINT de Dominios y Red](#8-osint-de-dominios-y-red)
9. [Inteligencia de Brechas y Filtraciones (HIBP)](#9-inteligencia-de-brechas-y-filtraciones-hibp)
10. [Wayback Machine en Profundidad](#10-wayback-machine-en-profundidad)
11. [Referencia de Extracción de PII y Secretos](#11-referencia-de-extracción-de-pii-y-secretos)
12. [Descargador de Medios](#12-descargador-de-medios)
13. [Gestión de Casos](#13-gestión-de-casos)
14. [Formatos de Exportación](#14-formatos-de-exportación)
15. [Gestión de Caché](#15-gestión-de-caché)
16. [Recetas de Investigación](#16-recetas-de-investigación)
17. [Solución de Problemas](#17-solución-de-problemas)
18. [Preguntas Frecuentes](#18-preguntas-frecuentes)
19. [Glosario](#19-glosario)

---

## 1. Primeros Pasos

### 1.1 Instalación

#### Linux / macOS / Windows

```bash
git clone https://github.com/kahz12/scannus.git
cd scannus
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

#### Termux (Android)

ScannUs corre sobre Termux con algunas salvedades:

```bash
pkg install python rust firefox
pip install -r requirements.txt
```

| Módulo | Estado en Termux |
|---|---|
| Sherlock | ✅ Python puro, funciona |
| Maigret | ❌ Fija `aiohttp==3.8.x` sin wheel para aarch64-android |
| Playwright | ❌ Sin Chromium para Android arm — recurre a Selenium |
| Selenium + geckodriver | ✅ `pkg install geckodriver` |
| pycryptodome | ✅ Para validación EIP-55 de Ethereum |

#### Dependencias del sistema

| Herramienta | Requerida para |
|---|---|
| **Firefox + geckodriver** | Capturas con Selenium, scraping profundo, imagen inversa, reproducción click-play |
| **Chromium + Playwright** | Motor de capturas preferido (más rápido y fiable) |
| **ollama** (opcional) | Proveedor de LLM local — solo si usas backend `Ollama` |

Instalar los navegadores de Playwright (opcional pero recomendado):

```bash
playwright install chromium
```

### 1.2 Primera Ejecución

```bash
python main.py
```

La primera ejecución hará lo siguiente:

1. Crear el árbol de directorios `outputs/`.
2. Verificar la existencia de `.env` — si falta, ofrecerte ejecutar el asistente.
3. Imprimir el banner con gradiente mostrando qué claves de API fueron detectadas.
4. Llevarte al menú principal de la TUI interactiva.

Si prefieres configurar primero:

```bash
python main.py -c
```

### 1.3 Asistente de Configuración

El asistente (`python main.py -c`) te guía por 7 secciones, solicitando una clave a la vez. Pulsa Enter para omitir cualquier campo.

```
┌─ Google Custom Search API ───────────────────────
│   API_KEY_GOOGLE      (desde console.cloud.google.com)
│   SEARCH_ENGINE_ID    (desde cse.google.com)
├─ Google AI (Gemini) ─────────────────────────────
│   GOOGLE_API_KEY_FOR_GEMINI (desde aistudio.google.com)
├─ Brave Search API ───────────────────────────────
│   BRAVE_API_KEY       (desde api.search.brave.com)
├─ Have I Been Pwned (HIBP) ───────────────────────
│   HIBP_API_KEY        (desde haveibeenpwned.com/API/Key)
├─ Anthropic Claude ───────────────────────────────
│   ANTHROPIC_API_KEY   (desde console.anthropic.com)
├─ Ollama (LLM local) ─────────────────────────────
│   OLLAMA_HOST         (por defecto: http://localhost:11434)
│   OLLAMA_MODEL        (por defecto: llama3)
└─ OpenAI ─────────────────────────────────────────
    OPENAI_API_KEY      (desde platform.openai.com)
```

Todos los valores se escriben en `.env` en la raíz del proyecto. Puedes editarlos a mano en cualquier momento.

#### Configuración mínima viable

Puedes usar ScannUs con **cero claves de API**:

- ✅ Búsqueda en DuckDuckGo
- ✅ Verificación de contraseñas con k-anonimato HIBP (gratis)
- ✅ Brechas de dominio HIBP (gratis)
- ✅ Consulta de brecha individual HIBP (gratis)
- ✅ Enumeración de subdominios vía crt.sh
- ✅ Wayback Machine
- ✅ WHOIS + DNS + TLS + cabeceras HTTP
- ✅ Enumeración de usuarios vía Sherlock
- ✅ Fingerprinting de tecnologías web
- ✅ Imagen inversa — URLs de respaldo manuales

Para desbloquear toda la potencia, añade como mínimo una clave de Gemini (capa gratuita) y una clave de Google Custom Search.

---

## 2. Conceptos Centrales

### 2.1 Modo Interactivo vs Modo CLI

ScannUs ofrece dos interfaces igualmente potentes:

**TUI Interactiva** — ideal para investigaciones donde cada paso informa al siguiente:

```bash
python main.py            # por defecto
python main.py -i         # explícito
```

**Modo CLI** — ideal para scripting, automatización y consultas puntuales:

```bash
python main.py --recon example.com --json out.json
python main.py --hibp-account objetivo@example.com
```

Cada flag de CLI tiene su entrada equivalente en el menú, y viceversa. La TUI internamente despacha a las mismas funciones que la CLI.

### 2.2 Casos

Un **caso** es una investigación con nombre — tu consulta, el motor usado, todos los resultados devueltos y una marca temporal de creación. Los casos viven en una base SQLite en `outputs/cases/cases.db`.

#### Guardar un caso

Después de que una búsqueda devuelva resultados, escribe `save` en el prompt de resultados. Se te pedirá un nombre. Si el nombre ya existe, se te pedirá confirmar la sobrescritura.

#### Cargar un caso

```bash
python main.py --load-case
```

O desde el menú principal → "Cargar Caso Guardado". Verás una lista de casos; elige uno para restaurar los resultados y entrar al menú de análisis.

#### Esquema del caso

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

### 2.3 La Caché Persistente

Toda llamada externa costosa pasa por una única caché SQLite en `outputs/cache/cache.db`. La caché:

- **Persiste entre sesiones** — reinicia tu terminal, la caché sobrevive.
- **Usa el modo journal WAL** — múltiples procesos pueden compartirla.
- **Tiene TTLs por namespace** — distintos tipos de contenido expiran a distintos ritmos.
- **Almacena JSON** — las fechas se serializan automáticamente como texto.

#### Namespaces y TTLs

| Namespace | TTL | Qué se cachea |
|---|---|---|
| `search` | 24h | Resultados SERP de todos los motores |
| `http_text` | 6h | Texto de página depurado |
| `whois` | 7d | Metadatos del registrador |
| `dns` | 1h | Registros A/AAAA/MX/NS/TXT/SOA/CAA |
| `wayback` | 30d | Capturas del archivo (inmutables de todos modos) |
| `crtsh` | 24h | Enumeración de subdominios vía CT-log |
| `hibp_account` | 12h | Consultas por email de brechas + pastes |
| `hibp_breach` | 7d | Metadatos de brechas, brechas por dominio, catálogo completo |
| `hibp_password` | 30d | Rangos SHA-1 con k-anonimato |

#### Saltarse la caché temporalmente

```bash
SCANNUS_CACHE_DISABLE=1 python main.py --recon example.com
```

Con esto desactivado, todas las lecturas devuelven `None` y las escrituras no hacen nada — útil para depuración.

#### Inspeccionar la caché

```bash
python main.py --cache-stats
```

Devuelve:

```
hits:        42
misses:      18
hit_ratio:   70.0%
rows:        103
by_namespace: {'search': 24, 'whois': 4, 'wayback': 41, ...}
db_path:     /ruta/a/outputs/cache/cache.db
db_size:     487424
disabled:    False
```

#### Limpiar la caché

```bash
python main.py --cache-clear              # borrar todo
python main.py --cache-clear wayback      # solo un namespace
python main.py --cache-clear hibp_account # invalidar consultas de brechas
```

### 2.4 Proveedores de IA

ScannUs soporta cuatro proveedores de IA, todos detrás de un contrato unificado `generate(prompt)` + `stream(prompt)`:

| Proveedor | Modelo | Coste | Configuración |
|---|---|---|---|
| **Google Gemini** | `gemini-2.0-flash` | Capa gratuita | `GOOGLE_API_KEY_FOR_GEMINI` |
| **OpenAI** | `gpt-4o` | De pago | `OPENAI_API_KEY` |
| **Anthropic** | `claude-sonnet-4-6` | De pago | `ANTHROPIC_API_KEY` |
| **Ollama** | `llama3` (configurable) | Gratis (local) | Daemon `OLLAMA_HOST` |

Los proveedores transmiten tokens en streaming — la salida aparece progresivamente en lugar de toda al final.

Sobrescribe cualquier modelo mediante variables de entorno:

```bash
ANTHROPIC_MODEL=claude-opus-4-7 python main.py -i
OLLAMA_MODEL=qwen2.5:7b python main.py -i
```

---

## 3. Búsqueda

### 3.1 Búsqueda Directa

El punto de entrada más común. Pasa cualquier cadena de búsqueda con `-q`:

```bash
python main.py -q "OSINT tools"
python main.py -q 'site:linkedin.com "project manager" "New York"'
python main.py -q 'filetype:xlsx "lista de precios" "productos electrónicos"'
```

Los operadores de Google Dorks se pasan tal cual:

| Operador | Efecto |
|---|---|
| `site:` | Restringir a un dominio |
| `filetype:` | Restringir a una extensión de archivo |
| `intitle:` | Coincidir en `<title>` |
| `inurl:` | Coincidir en la ruta de la URL |
| `"frase exacta"` | Coincidencia literal |
| `-excluir` | Excluir términos |
| `AND` / `OR` | Combinadores booleanos |

### 3.2 Búsqueda Guiada

Para OSINT sobre personas, construye una consulta `AND` compuesta de forma interactiva o por flags:

```bash
python main.py -n "Juan Pérez" -u "jperez88" -e "juan@corp.com" -t "+34-600-123-456"
```

La consulta resultante es:

```
"Juan Pérez" AND "jperez88" AND "juan@corp.com" AND "+34-600-123-456"
```

Si `-e` o `-t` están presentes, ScannUs cambia automáticamente al **modo de extracción profunda** — rastrea cada URL de resultado y ejecuta extracción de PII sobre el contenido.

Flags guiadas disponibles:

| Flag | Corta | Propósito |
|---|---|---|
| `--nombre` | `-n` | Nombre legal completo |
| `--usuario` | `-u` | Nombre de usuario / handle |
| `--email` | `-e` | Email (activa `--deep`) |
| `--telefono` | `-t` | Teléfono (activa `--deep`) |
| `--buscar` | `-b` | Palabra clave genérica |

### 3.3 Comparativa de Motores

| Motor | Autenticación | Pros | Contras |
|---|---|---|---|
| **DuckDuckGo** | Ninguna | Gratis, sin rate limits visibles | Scraping HTML — puede romperse con cambios de maquetación |
| **Google CSE** | API key + CX | Mejor calidad de resultados | 100 consultas gratis/día, luego $5 por 1000 |
| **Brave Search** | API key | Índice independiente, menos correlacionado con Google | Índice menor que Google |

Elige en tiempo de ejecución:

```bash
python main.py -q "consulta" --engine duckduckgo    # por defecto
python main.py -q "consulta" --engine google
python main.py -q "consulta" --engine brave
```

### 3.4 Paginación e Idiomas

```bash
python main.py -q "consulta" --pages 3              # traer 3 páginas
python main.py -q "consulta" --start-page 5         # empezar desde la página 5
python main.py -q "consulta" --lang lang_en         # solo inglés
python main.py -q "consulta" --lang lang_es         # español (por defecto)
```

---

## 4. Funciones de IA

### 4.1 Elección de Proveedor

Cuando la TUI necesita un agente de IA, muestra un selector. Desde la CLI, el proveedor se elige de forma perezosa — solo se inicia el agente que necesitas.

**Matriz de decisión:**

| Necesitas… | Elige |
|---|---|
| Mejor opción gratuita, iteración rápida | Gemini |
| Mayor calidad analítica | Claude o GPT-4o |
| Air-gapped / sensible a la privacidad | Ollama |
| Menor coste por token con alta calidad | Claude Sonnet 4.6 |
| Mejor uso de herramientas / salida estructurada | Claude o GPT-4o |

### 4.2 Generador de Dorks con IA

Convierte lenguaje natural en un dork de Google preciso:

```bash
python main.py -gd "Encontrar listas de precios en Excel de empresas de electrónica"
```

Transmite el dork en vivo a tu terminal:

```
filetype:xlsx "lista de precios" "electrónica" OR "electrónicos"
```

O por TUI: menú principal → **Generador de Dorks con IA**.

**Consejos para buenas descripciones:**

- Menciona los tipos de archivo explícitamente: "PDFs de contratos", "listas de precios en Excel"
- Menciona dominios/TLDs: ".gov", ".edu.co"
- Menciona exclusiones: "excluir sitios de marketing"

### 4.3 Planificador de Consultas con IA (ReAct)

El planificador toma un objetivo en lenguaje natural y produce un **plan de investigación multi-paso** compuesto por llamadas a herramientas en lista blanca. Cada paso es confirmable interactivamente, y el planificador puede replanificar tras cada observación.

```bash
python main.py -p "Investigar brechas que afectan a acme.com y encontrar PII filtrada"
```

Un plan típico se ve así:

```
Resumen del plan: Reconocer el dominio objetivo, enumerar exposición a brechas,
                  luego rastrear superficie de PII filtrada.

Paso 1/5 · domain_recon
  por qué: Establecer línea base (WHOIS, DNS, TLS, cabeceras, subdominios)
  espera: Stack tecnológico y panorama de infraestructura
  args:   {'target': 'acme.com'}
  ¿Ejecutar este paso? [S/n]

Paso 2/5 · hibp_domain
  por qué: Comprobar si acme.com ha aparecido en alguna brecha registrada
  ...
```

Puedes:

- **Aceptar** cada paso → se ejecuta; los resultados se resumen e imprimen.
- **Saltar** un paso → el planificador continúa.
- **Abortar** a mitad del plan → ScannUs registra las observaciones y puede replanificar.

El plan se guarda en el caso actual para que puedas reproducirlo más tarde.

### 4.4 El Catálogo de Herramientas

El planificador solo puede invocar herramientas en lista blanca. A la fecha de esta guía, hay 22 herramientas expuestas:

| Herramienta | Propósito |
|---|---|
| `search` | Ejecutar una búsqueda SERP |
| `deep_search` | Búsqueda + crawl + extracción de PII |
| `extract_pii` | Rastrear una URL y extraer PII |
| `tech_scan` | Fingerprinting de tecnologías web |
| `username_enum` | Enumeración Sherlock/Maigret |
| `email_enum` | Búsqueda de registros en ~120 servicios vía Holehe |
| `screenshot` | Captura de página completa |
| `wayback` | Timeline de capturas |
| `wayback_fetch` | Obtener contenido archivado en bruto |
| `wayback_extract` | Extracción de PII sobre una captura |
| `wayback_diff` | Diff entre dos capturas |
| `summarize_url` | Resumen con IA de una URL |
| `domain_recon` | Barrido completo de OSINT de dominio |
| `whois` | Consulta WHOIS |
| `dns_records` | Registros DNS |
| `tls_certificate` | Inspección de certificado TLS |
| `http_security_headers` | Cabeceras HTTP de hardening |
| `subdomains` | Enumeración crt.sh por CT-log |
| `reverse_image` | Imagen inversa multi-motor |
| `hibp_account` | Búsqueda de brecha por cuenta HIBP |
| `hibp_domain` | Brechas por dominio HIBP (gratis) |
| `hibp_breach` | Metadatos de una brecha individual (gratis) |
| `hibp_password` | Pwned Passwords con k-anonimato (gratis) |

Cada herramienta devuelve `{status, summary, data}`. El planificador ve el resumen y lo usa para informar el siguiente paso.

---

## 5. Análisis por URL

Tras una búsqueda verás una tabla paginada. Escribe el ID de un resultado para abrir el **Submenú de Análisis de URL**, que ofrece 10 opciones de exploración profunda para esa URL.

### 5.1 Resumir Contenido

```
Análisis de URL → Resumir contenido (IA)
```

Obtiene la página, extrae el texto limpio (pipeline trafilatura → readability → BeautifulSoup), lo trocea si hace falta (ventanas de 12 KB con solape de 500 caracteres) y alimenta cada trozo al proveedor de IA seleccionado. La salida se transmite a la terminal y se renderiza en un panel con borde verde.

### 5.2 Extraer PII

```
Análisis de URL → Extraer PII
```

Obtiene la página y ejecuta la **batería de regex de secretos + PII** sobre el texto. Mira la [Referencia de Extracción de PII y Secretos](#11-referencia-de-extracción-de-pii-y-secretos) para la lista completa de categorías detectadas.

Salida:

```
╭──────────────────────────────────────────────────╮
│ PII Extraído                                     │
├──────────────────────────────────────────────────┤
│ Emails       │ alicia@acme.com                   │
│              │ borja@acme.com                    │
│ Teléfonos    │ +34-600-123-456                   │
│ Iban         │ ES9121000418450200051332          │
│ Aws_keys     │ AKIAIOSFODNN7EXAMPLE              │
│ Github_pat   │ ghp_aBcDeFgHiJ…                   │
│ Btc_wallets  │ 1A1zP1eP5QGefi2DMPTfTL5SLmv7…     │
╰──────────────────────────────────────────────────╯
```

### 5.3 Escaneo de Tecnologías Web

```
Análisis de URL → Escanear tecnologías web
```

Ejecuta Wappalyzer (preferido) o webtech (de respaldo) contra la URL e imprime una tabla categorizada:

```
CMS              WordPress 6.4
Framework        React 18.2
Servidor web     nginx 1.25
CDN              Cloudflare
Analítica        Google Analytics, Mixpanel
Tag managers     Google Tag Manager
```

También disponible de forma independiente:

```bash
python main.py -i    # luego elige "Escaneo de Tecnologías Web"
```

### 5.4 Descargar Archivo

```
Análisis de URL → Descargar archivo
```

Descarga HTTP directa de la URL con extracción automática de metadatos:

| Tipo de archivo | Metadatos extraídos |
|---|---|
| PDF | Título, autor, creador, productor, fecha de creación, número de páginas |
| DOCX | Propiedades core (título, autor, last-modified-by, etc.) |
| XLSX | Propiedades del libro de trabajo |
| Imágenes | EXIF (modelo de cámara, GPS, marca temporal, software) |

Se guarda en `outputs/downloads/<tipo>/`.

### 5.5 Descargar Medios

```
Análisis de URL → Descargar medios
```

Dispara el **descargador de medios de tres niveles** (mira la [Sección 12](#12-descargador-de-medios)). Te preguntará:

1. **Tipo de medio** — `all`, `images`, `videos` o `audio`
2. **¿Usar Selenium para páginas con JS?** — `s`/`N`

Salida: un archivo ZIP estructurado en `outputs/media/`.

### 5.6 Capturar Pantalla

```
Análisis de URL → Capturar pantalla
```

Selecciona automáticamente el motor de capturas:

1. **Playwright (Chromium)** — preferido. El más fiable; maneja web moderna.
2. **Selenium (Firefox headless)** — respaldo. Redimensiona la ventana a la altura total del documento para una PNG de página completa de un solo disparo.

Se guarda en `outputs/screenshots/<host_slug>_<timestamp>.png`.

### 5.7 Wayback Machine

```
Análisis de URL → Historial Wayback Machine
```

Consulta la API CDX de Internet Archive para obtener la línea temporal de capturas de la URL. Renderiza una tabla de marcas temporales + códigos de estado + tipos MIME.

Para flujos más profundos con Wayback, mira la [Sección 10](#10-wayback-machine-en-profundidad).

### 5.8 Análisis Profundo con IA

```
Análisis de URL → Análisis profundo con IA
```

Como Resumir, pero con un prompt orientado a OSINT. Se le pide a la IA que extraiga:

- Personas, organizaciones, ubicaciones mencionadas
- Relaciones implícitas ("X trabaja para Y", "A reporta a B")
- Pistas de investigación ("se menciona el email de Y — prueba el patrón de formato")
- Puntos clave de inteligencia

Se renderiza en un panel con borde amarillo.

### 5.9 Grafo de Relaciones entre Entidades

```
Análisis de URL → Grafo de relaciones entre entidades
```

La IA extrae entidades y sus relaciones en JSON estructurado; Pyvis renderiza un grafo HTML interactivo. Salida: `outputs/graphs/graph_<host>.html`.

Ábrelo en cualquier navegador para explorar, hacer zoom y arrastrar los nodos.

### 5.10 Scraping Profundo (Renderizado JS)

```
Análisis de URL → Scraping profundo
```

Para Single-Page Applications y sitios con mucho JS que el HTTP estático no puede alcanzar:

1. Levanta Firefox headless vía Selenium.
2. Carga la URL, espera a `document.readyState === 'complete'`.
3. Hace scroll hasta el final (dispara cargas lazy).
4. Extrae el texto del DOM renderizado.
5. Ejecuta la extracción de PII contra el texto renderizado.

Más lento que el fetching estático pero revela contenido que de otro modo es invisible para los scrapers.

---

## 6. Búsqueda Inversa de Imágenes

Orquestador multi-motor y multi-nivel. Siempre devuelve *algo* porque el nivel de URLs manuales nunca falla.

```bash
python main.py -rev https://example.com/foto.jpg
```

O vía TUI: menú principal → **Búsqueda Inversa de Imagen**.

### Desglose por niveles

| Nivel | Motor | Autenticación | Qué devuelve |
|---|---|---|---|
| 1 | **TinEye** | `TINEYE_PUBLIC_KEY` + `TINEYE_PRIVATE_KEY` | Coincidencias exactas, dominios espejo |
| 2 | **Bing Visual Search** | `BING_VISUAL_API_KEY` | Imágenes visualmente similares |
| 3 | **Yandex** | Ninguna (scraping HTML vía Selenium) | Fuerte para coincidencia facial, contenido de Europa del Este |
| 4 | **Respaldo manual** | Ninguna | URLs a Google Lens, Bing, Yandex, TinEye, SauceNAO con la imagen pre-rellenada |

### Salida de ejemplo

```
Imagen inversa: 14 entradas (tineye×2, bing×3, yandex×4, manual×5)
```

### Lista blanca de motores

```bash
python main.py -rev https://example.com/foto.jpg
# (interactivo — automático)

# O en un paso de plan:
{"tool": "reverse_image",
 "args": {"url": "https://example.com/foto.jpg",
          "engines": ["tineye", "yandex", "manual"]}}
```

---

## 7. Enumeración de Usuarios

Verifica un nombre de usuario contra 400+ sitios (Sherlock) o 3000+ sitios (Maigret) sociales.

```bash
python main.py --username-enum jperez88
python main.py --username-enum jperez88 --enum-backend sherlock
python main.py --username-enum jperez88 --enum-backend maigret    # solo Linux/macOS
python main.py --username-enum jperez88 --enum-backend auto       # prefiere Sherlock
```

O TUI: menú principal → **Enumeración de Usuarios**. Te pedirá:

1. El nombre de usuario/handle
2. Backend (auto/sherlock/maigret)
3. Timeout por sitio (por defecto 20s)

### Comparativa

| Backend | Sitios | Velocidad | Termux | Python 3.13 |
|---|---|---|---|---|
| **Sherlock** | ~400 | Rápido (concurrente) | ✅ | ✅ |
| **Maigret** | ~3000 | Más lento (más exhaustivo) | ❌ | ⚠️ Fija aiohttp 3.8.x |

Los resultados se renderizan en una tabla:

```
╭─────────────┬───────────────────────────────────╮
│ Sitio       │ URL                               │
├─────────────┼───────────────────────────────────┤
│ GitHub      │ https://github.com/jperez88       │
│ Twitter     │ https://twitter.com/jperez88      │
│ Reddit      │ https://reddit.com/user/jperez88  │
╰─────────────┴───────────────────────────────────╯
```

### 7.1 Enumeración de Emails (Holehe)

El equivalente de Sherlock/Maigret para correos electrónicos. Dado un email,
**Holehe** sondea ~120 servicios (Instagram, Twitter, Pinterest, Spotify,
Adobe, Pornhub, …) mediante sus flujos de recuperación de contraseña y
reporta dónde está registrada la dirección — *sin enviar ningún correo al
objetivo*.

```bash
python main.py --email-enum objetivo@example.com              # solo servicios reclamados
python main.py --email-enum objetivo@example.com --email-enum-all   # reporte completo
```

TUI: menú principal → **Enumeración de Emails**.

**En qué se diferencia de herramientas relacionadas:**

| Herramienta | Qué responde |
|---|---|
| `--hibp-account` | *¿Este email apareció en alguna filtración conocida?* |
| `--email-enum` (Holehe) | *¿Dónde está registrado este email hoy?* |
| `-e/--email` (PII profundo) | *¿Qué dice la web sobre este email — páginas, menciones, PII?* |

Los resultados se cachean 12h bajo el namespace `email_enum`, así que reejecutar
la misma búsqueda es instantáneo.

**Limitaciones:**

- Los detectores por sitio se degradan a medida que los servicios cambian sus
  flujos de recuperación — espera falsos negativos ocasionales. Fija una
  versión conocida de `holehe` en `requirements.txt`.
- Algunos sitios aplican rate-limit silenciosamente; los resultados de una
  sola ejecución pueden subreportar. Vuelve a intentarlo tras unos minutos
  si una cuenta conocida no aparece.
- **No** lo uses para enumeración masiva: los rate limits + captchas te bloquearán.

**Instalación:** `pip install holehe`. Si falta, `--email-enum` imprime una
sugerencia amistosa de instalación y sale limpiamente.

---

## 8. OSINT de Dominios y Red

```bash
python main.py --recon example.com
```

Ejecuta el **barrido completo de reconocimiento** en un solo comando:

```
┌─ WHOIS ─────────────────────────────────
│  Registrador: ICANN
│  Creado:     1995-08-13
│  Expira:     2026-08-12
│  ...
├─ Registros DNS ────────────────────────
│  A      →  93.184.216.34
│  AAAA   →  2606:2800:220:1:248:1893:25c8:1946
│  MX     →  10 mail.example.com
│  NS     →  a.iana-servers.net, b.iana-servers.net
│  ...
├─ Seguridad de email ───────────────────
│  SPF       →  v=spf1 -all
│  DMARC     →  v=DMARC1; p=reject; rua=mailto:...
│  Pista DKIM →  default._domainkey.example.com  (no encontrada)
├─ Certificado TLS ──────────────────────
│  Sujeto    →  www.example.com
│  SANs      →  www.example.com, example.com
│  Válido hasta: 2026-03-15  (245 días restantes)
│  Cifrado   →  TLS_AES_256_GCM_SHA384  (TLSv1.3)
├─ Cabeceras HTTP de seguridad ──────────
│  Puntuación: 6/10
│  HSTS       ✓   max-age=31536000
│  CSP        ✓   presente
│  COOP       ✗   ausente
│  COEP       ✗   ausente
│  X-Frame    ✓   SAMEORIGIN
│  ...
├─ Subdominios (crt.sh) ─────────────────
│  47 subdominios descubiertos
│  api.example.com, dev.example.com, staging…
└─ Consulta de host en Shodan ───────────
   Puertos: 80, 443, 8080
   Servicios: nginx, ssh
```

### Primitivas individuales

Puedes ejecutar cada pieza por separado desde la TUI:

| Entrada de menú | Qué hace |
|---|---|
| Recon completo | Las siete |
| WHOIS | Solo metadatos del registrador |
| Registros DNS | Todos los tipos de registro |
| Seguridad de email (SPF/DMARC) | Autenticación de correo |
| Certificado TLS | Cadena de cert + validez |
| Cabeceras HTTP de seguridad | Puntuación de cabeceras de hardening |
| Subdominios (crt.sh) | Enumeración pasiva CT-log |
| Consulta de host Shodan | Banners de servicios (requiere `SHODAN_API_KEY`) |

### TTLs de caché para recon

WHOIS rara vez cambia (cacheado 7d). DNS cambia con frecuencia (cacheado 1h). crt.sh es append-only (cacheado 24h).

---

## 9. Inteligencia de Brechas y Filtraciones (HIBP)

ScannUs integra toda la superficie de la API de Have I Been Pwned más el endpoint gratuito de Pwned Passwords con k-anonimato.

### 9.1 Consulta por cuenta (de pago)

```bash
python main.py --hibp-account objetivo@example.com
```

Requiere `HIBP_API_KEY`. Devuelve:

- **Brechas** que contienen este email
- **Pastes** que referencian este email (Pastebin, GitHub Gist, etc.)

Salida de ejemplo:

```
╭──────────────────────────────────────────────────────────────╮
│ Brechas para objetivo@example.com  (3 coincidencias)         │
├──────────┬────────────┬──────────┬─────────────┬─────────────┤
│ Nombre   │ Dominio    │ Fecha    │ Cuentas     │ Datos       │
├──────────┼────────────┼──────────┼─────────────┼─────────────┤
│ Adobe    │ adobe.com  │ 2013-10  │ 152,445,165 │ Email…      │
│ LinkedIn │ linkedin.. │ 2012-05  │ 164,611,595 │ Email…      │
│ Dropbox  │ dropbox..  │ 2012-07  │  68,648,009 │ Email…      │
╰──────────┴────────────┴──────────┴─────────────┴─────────────╯
```

### 9.2 Consulta por dominio (gratis)

```bash
python main.py --hibp-domain example.com
```

No requiere clave de API. Lista cada brecha registrada que afecte al dominio. Útil para una verificación rápida de la higiene de una empresa.

### 9.3 Detalles de una brecha (gratis)

```bash
python main.py --hibp-breach Adobe
python main.py --hibp-breach LinkedIn
```

Devuelve metadatos completos de la brecha incluyendo el texto descriptivo, flag de sensibilidad y la lista exacta de clases de datos que se filtraron.

### 9.4 Pwned Passwords (gratis, seguro)

```bash
python main.py --hibp-password
```

Se te pedirá una contraseña con **entrada oculta** (sin eco en terminal). El texto plano se hashea localmente con SHA-1; solo los primeros 5 caracteres hex del hash se envían a `api.pwnedpasswords.com`. El hash completo nunca sale de tu proceso.

Salidas de ejemplo:

```
✔  La contraseña no se encontró en ningún corpus HIBP conocido.
```

```
⚠  Contraseña vista en el corpus HIBP: 3 vez/veces — cámbiala.
```

```
✘  Contraseña vista en el corpus HIBP: 9.999.999 vez/veces — NO la uses en ningún sitio.
```

### 9.5 Garantía de privacidad

| Lo que nunca ocurre | Lo que sí ocurre |
|---|---|
| La contraseña en texto plano sale de tu máquina | El hash SHA-1 se calcula localmente |
| Se envía el hash completo a HIBP | Se envían los 5 primeros caracteres hex a HIBP |
| El texto plano se registra en algún sitio | El texto plano se descarta inmediatamente después de hashear |

Puedes verificar esto ejecutando un sniffer de paquetes (`tcpdump`, `wireshark`) mientras invocas `--hibp-password`. Solo el prefijo aparece en el tráfico saliente.

---

## 10. Wayback Machine en Profundidad

### 10.1 Consulta de línea temporal

```bash
python main.py -q "site:example.com"
# selecciona un resultado → Análisis de URL → Historial Wayback Machine
```

Devuelve una tabla de capturas: marca temporal, código de estado, tipo MIME.

### 10.2 Obtener una captura

Disponible vía el Planificador de Consultas con IA con la herramienta `wayback_fetch`, o programáticamente:

```python
from analysis.advanced_osint import wayback_fetch_snapshot
snap = wayback_fetch_snapshot("https://example.com", "20200615")
# {timestamp, date, archive_url, status, mime, size, text}
```

Formatos de marca temporal aceptados:

| Entrada | Significado |
|---|---|
| `latest` | Captura más reciente |
| `earliest` | Primera captura existente |
| `2020` | Captura más cercana al año 2020 |
| `2020-06` | La más cercana a junio de 2020 |
| `20200615` | Fecha (YYYYMMDD) |
| `20200615120000` | Marca CDX completa de 14 dígitos |

### 10.3 Extracción de PII sobre una captura

Herramienta: `wayback_extract`. Obtiene una captura y ejecuta toda la batería de PII/secretos sobre ella. Surfacea identificadores que han sido eliminados del sitio en producción.

```
Paso del plan: {
  "tool": "wayback_extract",
  "args": {"url": "https://example.com/equipo", "timestamp": "2019"}
}
```

### 10.4 Diff entre capturas

Herramienta: `wayback_diff`. Renderiza un diff unificado entre dos capturas:

```
{
  "tool": "wayback_diff",
  "args": {"url": "https://example.com/sobre-nosotros",
           "ts_a": "2018", "ts_b": "latest"}
}
```

Salida:

```
2018-01-15 -> 2024-08-03: +127 -83
+ Teléfono: +34-600-909-090
+ Email: contacto@nuevaco.example
- Teléfono: +34-600-012-345
- Oficina: Calle Vieja 123
```

Las capturas con huellas digitales de contenido idénticas (SHA-256) se marcan con `(idéntica)`.

---

## 11. Referencia de Extracción de PII y Secretos

El motor de extracción de ScannUs detecta y valida **25+ categorías de identificadores**. Todos los validadores comprueban estructura Y checksums cuando aplica.

### PII estándar

| Categoría | Validación |
|---|---|
| **Emails** | Regex + decodificación de ofuscación (`[at]`, `(dot)`, `&#64;`, con espacios); filtro de falsos positivos excluye `noreply@*`, bots, dominios de prueba |
| **Teléfonos** | libphonenumber (internacional, consciente del país) |

### Documentos de identidad

| Categoría | Validación |
|---|---|
| **SSN de EE. UU.** | Regex + rechaza área 000/666/9xx, grupo 00, serie 0000 |
| **CPF brasileño** | Checksum de dos dígitos módulo 11; rechaza dígitos todos iguales |
| **SIN canadiense** | Algoritmo Luhn |
| **DNI/CUIT argentinos** | Estructural |
| **RFC mexicano** | Estructural |

### Financiero

| Categoría | Validación |
|---|---|
| **IBAN** | Regex por código de país + checksum |
| **Tarjetas de crédito** | Algoritmo Luhn |

### Secretos de nube y API

| Categoría | Patrón |
|---|---|
| **AWS** | `AKIA…` / `ASIA…` + 16 caracteres |
| **GitHub PAT** | `ghp_` / `ghu_` / `gho_` / `ghr_` / `ghs_` + 36 caracteres; o `github_pat_` + 82 caracteres |
| **GitLab PAT** | `glpat-` + 20 caracteres |
| **Tokens Slack** | `xoxa-` / `xoxb-` / `xoxp-` / `xoxr-` / `xoxs-` |
| **Stripe** | `(sk\|rk\|pk)_(live\|test)_…` |
| **Google API** | `AIza` + 35 caracteres |
| **Bot de Discord** | Patrón de token |
| **Bot de Telegram** | `<dígitos>:<35 caracteres>` |
| **Claves privadas PEM** | `-----BEGIN…PRIVATE KEY-----` |
| **JWTs** | Cabecera decodificada; requiere campo `alg` válido |

### Carteras cripto

| Categoría | Validación |
|---|---|
| **Bitcoin P2PKH/P2SH** | base58check decode + checksum |
| **Bitcoin Bech32** | Regex (`bc1q…`) |
| **Ethereum** | Checksum EIP-55 mixed-case con Keccak-256 (vía pycryptodome) |

### Red

| Categoría | Validación |
|---|---|
| **IPv4 pública** | `ipaddress` de stdlib; filtra privadas, loopback, link-local, multicast |
| **IPv6 pública** | `ipaddress` de stdlib; mismos filtros |
| **MAC** | `XX:XX:XX:XX:XX:XX` o `XX-XX-…` |

### Ejemplo de salida de extracción

```python
from search.smart_search import extract_information

text = """
Contacto: alicia@acme.com o llamar al +34-600-123-456
AWS: AKIAIOSFODNN7EXAMPLE
JWT: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
BTC: 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa
ETH: 0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed
"""

print(extract_information(text))
# {
#   "emails":      {"alicia@acme.com"},
#   "phones":      {"+34-600-123-456"},
#   "aws_keys":    {"AKIAIOSFODNN7EXAMPLE"},
#   "jwts":        {"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."},
#   "btc_wallets": {"1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"},
#   "eth_wallets": {"0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"},
# }
```

---

## 12. Descargador de Medios

Estrategia de fallback de tres niveles. Cada nivel se intenta en orden; si falla, ScannUs pasa al siguiente.

### Nivel 1: yt-dlp (1000+ plataformas)

El primer intento. Cubre YouTube, Vimeo, TikTok, Twitter/X, Instagram, Twitch, Facebook, más de 1000 sitios de nicho. Maneja streams adaptativos HLS/DASH.

### Nivel 2: Reproducción click-play con Selenium

Para reproductores de video personalizados (CMS propietario, reproductores con paywall). ScannUs:

1. Levanta Firefox headless
2. Encuentra el elemento `<video>`
3. Hace clic en el botón de play
4. Espera 2 segundos a que se llene el atributo `src`
5. Lee la URL resuelta y la descarga

### Nivel 3: HTML estático

Para páginas con `<video src="…">` enlazado directamente que no requieren JS. El caso más simple.

### Uso

```bash
python main.py --media-scrape "https://example.com/galeria"
```

O desde el menú por-URL tras una búsqueda → "Descargar medios".

Te preguntará:

1. **Tipo de medio** — `all`, `images`, `videos`, `audio`
2. **¿Usar Selenium para páginas con JS?** — `s` si el sitio es rico en JS

### Características

- **Concurrente** — `ThreadPoolExecutor` paraleliza las descargas
- **Consciente del MIME** — clasifica en subdirectorios `images/`, `videos/`, `audio/`
- **Mínimo 5 KB** — filtra píxeles de tracking y respuestas vacías
- **Reintentos con backoff** — 3 intentos con retraso exponencial
- **Empaquetado en ZIP** — la salida final es un único archivo estructurado

---

## 13. Gestión de Casos

### Guardar

Después de ejecutar una búsqueda, escribe `save` en el prompt de resultados:

```
> save
Introduce nombre del caso: jperez-investigacion-2025-03
✓ Caso 'jperez-investigacion-2025-03' guardado (47 resultados)
```

Si el nombre ya existe, se te pedirá confirmar la sobrescritura:

```
El caso 'jperez-investigacion-2025-03' ya existe. ¿Sobrescribir? [s/N]
```

### Cargar

```bash
python main.py --load-case
```

O menú principal → **Cargar Caso Guardado**.

Verás todos los casos con marcas temporales:

```
╭──┬───────────────────────────────────┬─────────────────────╮
│ #│ Nombre                            │ Creado              │
├──┼───────────────────────────────────┼─────────────────────┤
│ 1│ jperez-investigacion-2025-03      │ 2025-03-14 18:42:01 │
│ 2│ acme-corp-recon                   │ 2025-03-10 09:15:22 │
│ 3│ campana-phishing-leak             │ 2025-02-28 23:11:09 │
╰──┴───────────────────────────────────┴─────────────────────╯
```

Selecciona por ID; los resultados se restauran y se abre el menú de análisis.

### Actualizar

Después de cargar un caso, ejecuta búsquedas adicionales. Los nuevos resultados se fusionan. Escribe `save` de nuevo para actualizar.

### Eliminar

```
Menú principal → Cargar Caso Guardado → elegir → eliminar
```

O directamente vía SQL:

```bash
sqlite3 outputs/cases/cases.db "DELETE FROM cases WHERE name='casoviejo';"
```

---

## 14. Formatos de Exportación

### Excel (`.xlsx`)

```bash
python main.py -q "consulta" --excel resultados.xlsx
```

Características:
- Fila de cabecera con estilo (negrita, fondo coloreado)
- Colores de fila alternantes para legibilidad
- Hipervínculos clicables en la columna URL
- Ancho de columna auto-ajustado
- Se guarda en `outputs/reports/`

### CSV (`.csv`)

```bash
python main.py -q "consulta" --csv resultados.csv
```

Texto plano separado por comas. Se abre limpiamente en Excel, LibreOffice, pandas, R.

### JSON (`.json`)

```bash
python main.py -q "consulta" --json resultados.json
```

Array estructurado de objetos:

```json
[
  {"id": 1, "title": "…", "description": "…", "link": "https://…"},
  {"id": 2, ...}
]
```

### HTML (`.html`)

```bash
python main.py -q "consulta" --html reporte.html
```

Reporte estilizado autocontenido. Sin assets externos — compártelo por email.

### Varios a la vez

```bash
python main.py -q "consulta" --excel out.xlsx --json out.json --html out.html
```

---

## 15. Gestión de Caché

### Inspeccionar

```bash
python main.py --cache-stats
```

Muestra hits, misses, ratio de aciertos, conteos de filas por namespace y tamaño del archivo de BD.

### Limpiar

```bash
python main.py --cache-clear              # todo
python main.py --cache-clear search       # solo SERPs
python main.py --cache-clear http_text    # solo contenido de páginas
python main.py --cache-clear hibp_account # invalidar consultas de brechas
python main.py --cache-clear wayback      # raro — los archivos son inmutables
```

### Saltar

```bash
SCANNUS_CACHE_DISABLE=1 python main.py …
```

Cuando la variable de entorno está activa:
- Todos los `get()` devuelven `None` (cache miss)
- Todos los `set()` son no-op
- Las llamadas de red siempre se ejecutan

### Acceso programático

```python
from core.cache import get_cache, cached_call

cache = get_cache()
cache.set("custom", "key1", {"data": "…"}, ttl=3600)
value = cache.get("custom", "key1")

# Helper de alto nivel
result = cached_call(
    "namespace",
    ["clave", "partes"],
    lambda: funcion_costosa(),
    ttl=86400,
)
```

---

## 16. Recetas de Investigación

Flujos de trabajo de extremo a extremo combinando varias funciones de ScannUs.

### Receta 1: Investigando el email filtrado de un empleado

Objetivo: alguien te envió `objetivo@acme.com` como pista de phishing. Averiguar quién es, a qué tiene acceso y si sus credenciales se han filtrado.

```bash
# 1. ¿Ha estado el email en alguna brecha?
python main.py --hibp-account objetivo@acme.com

# 2. ¿Cuál es la postura de seguridad de la empresa?
python main.py --recon acme.com

# 3. ¿Hay otros emails con el mismo patrón?
python main.py -q '"objetivo" site:acme.com' --deep

# 4. Encontrar las cuentas sociales de la persona
python main.py --username-enum objetivo

# 5. Guardar todo
python main.py -i      # → save → "objetivo-acme-investigacion"
```

O deja que el planificador de IA lo orqueste:

```bash
python main.py -p "Investigar objetivo@acme.com — brechas, presencia social, postura de seguridad de la empresa, PII relacionada"
```

### Receta 2: Reconocimiento para una operación de seguridad

```bash
python main.py --recon objetivo.com --json recon.json
python main.py --hibp-domain objetivo.com
python main.py -q "site:objetivo.com filetype:pdf" --pages 3 --excel pdfs.xlsx
python main.py -q "site:objetivo.com inurl:admin OR inurl:login"
```

### Receta 3: Recuperación histórica de una página

Una página ha sido editada; encuentra qué se eliminó.

```bash
python main.py -i
# Menú principal → Búsqueda Directa → "site:objetivo.com/equipo"
# Elige resultado → Historial Wayback Machine → anota dos marcas temporales interesantes
# Usa el Planificador con objetivo:
#   "Hacer diff de la página del equipo entre 2018 y ahora y extraer cualquier PII de la versión más antigua"
```

El planificador invocará `wayback_diff` y `wayback_extract` en secuencia.

### Receta 4: Verificar una imagen sospechosa

Alguien te envió una foto de "[Persona X]". Verifica que sea auténtica.

```bash
python main.py -rev https://example.com/sospechosa.jpg
```

La imagen inversa multi-motor devuelve coincidencias de TinEye, Bing Visual, Yandex, más URLs de búsqueda manual. Si TinEye devuelve apariciones previas de la imagen (con marcas temporales), la imagen no es original.

### Receta 5: Auditoría de higiene de contraseñas

Para una lista de tus propias contraseñas antiguas (almacenadas offline), comprueba cada una contra HIBP sin enviarlas nunca a ningún sitio:

```bash
for pw in "p1" "p2" "p3"; do
  echo "$pw" | python main.py --hibp-password
done
```

Cada invocación hashea localmente y solo envía el prefijo de 5 caracteres.

### Receta 6: Traspaso de una investigación

Has hecho parte del trabajo. Ahora se lo pasas a un colega.

```bash
python main.py -i
# Ejecutar búsquedas, extraer URLs en profundidad, construir tablas de PII
# → save → "caso-2025-03-acme"

# Luego exportar todo para el colega:
python main.py -q "<consulta original>" --excel traspaso.xlsx --html traspaso.html --json traspaso.json
```

El colega luego puede hacer `--load-case` para retomar exactamente donde lo dejaste.

---

## 17. Solución de Problemas

### "Firefox no encontrado" / "falta geckodriver"

Selenium necesita Firefox + geckodriver en el `PATH`. En Linux:

```bash
sudo apt install firefox-esr
# geckodriver: descarga desde github.com/mozilla/geckodriver/releases
# colócalo en /usr/local/bin/
```

En Termux:

```bash
pkg install firefox geckodriver
```

ScannUs buscará geckodriver primero en `/data/data/com.termux/files/usr/bin/geckodriver`; si no, recurre a la búsqueda por PATH.

### "Chromium de Playwright no instalado"

```bash
playwright install chromium
```

Si no puedes instalar Playwright (p. ej., en Termux), ScannUs recurre automáticamente a Selenium con Firefox.

### "Falta GOOGLE_API_KEY_FOR_GEMINI"

Ejecuta el asistente:

```bash
python main.py -c
```

O edita `.env` directamente. Consigue una clave gratuita en https://aistudio.google.com.

### "Daemon de Ollama no accesible en http://localhost:11434"

Inicia el daemon:

```bash
ollama serve &
ollama pull llama3      # si todavía no lo tienes
```

O apunta a un Ollama remoto:

```bash
export OLLAMA_HOST=http://10.0.0.5:11434
python main.py -i
```

### "ANTHROPIC_API_KEY no definida"

```bash
python main.py -c
# (introduce tu clave en la sección de Anthropic)
```

O:

```bash
export ANTHROPIC_API_KEY=sk-ant-…
python main.py -i
```

### La caché devuelve datos obsoletos

```bash
python main.py --cache-clear <namespace>
```

O sáltatela por completo:

```bash
SCANNUS_CACHE_DISABLE=1 python main.py …
```

### "Módulo no encontrado: phonenumbers" / "Módulo no encontrado: pycryptodome"

```bash
pip install -r requirements.txt
```

Si estás en Termux y un wheel no compila, prueba:

```bash
pip install --no-build-isolation phonenumbers
```

### Las pruebas de Selenium abren una ventana del navegador

Asegúrate de no estar definiendo `MOZ_HEADLESS=0`. Headless es el valor por defecto; si ha sido sobrescrito, desactívalo:

```bash
unset MOZ_HEADLESS
```

### "Falla la instalación de Maigret"

Maigret fija `aiohttp==3.8.x` que no tiene wheels para aarch64-android. **En Termux usa Sherlock en su lugar**:

```bash
python main.py --username-enum jperez88 --enum-backend sherlock
```

### Salida de log excesiva

ScannUs es deliberadamente verboso por transparencia. Para acallarlo:

```bash
python main.py … 2>/dev/null         # suprimir avisos
python main.py … 2>&1 | tail -n 20   # solo las últimas 20 líneas
```

---

## 18. Preguntas Frecuentes

**P: ¿Es legal usar ScannUs?**

R: ScannUs solo consulta datos públicamente accesibles: motores de búsqueda, Internet Archive, logs CT públicos, registros WHOIS públicos, etc. Si tu *uso* es legal depende de tu jurisdicción y el propósito. Pruebas de seguridad autorizadas, periodismo, OSINT lícito y auditorías de higiene de tus propias cuentas son usos típicos justos. Apuntar a individuos o sistemas sin autorización puede violar leyes de abuso informático, anti-stalking o protección de datos en tu país. **Tú eres responsable del cumplimiento.**

**P: ¿ScannUs guarda mis consultas o las envía a un servidor?**

R: No. ScannUs corre enteramente en tu máquina. El único tráfico saliente es:
- Tus consultas directas a los motores de búsqueda que has configurado
- Peticiones a la API de HIBP (para consultas de brechas)
- Peticiones a Wayback Machine
- Llamadas opcionales a proveedores de IA (Gemini/OpenAI/Claude) si usas funciones de IA
- Llamadas opcionales a Ollama (local, tu daemon)

Sin telemetría, sin analítica, sin "phone home".

**P: ¿Cuánto suman los costes de API?**

Estimaciones aproximadas para uso moderado (50 investigaciones/mes):

| Servicio | Coste |
|---|---|
| Gemini | Gratis (la capa gratuita tiene límites generosos) |
| OpenAI GPT-4o | ~$2-5/mes |
| Anthropic Claude | ~$2-5/mes |
| Ollama | $0 (local) |
| HIBP (de pago) | $3,50/mes a tanto alzado |
| Google Custom Search | Primeras 100 consultas/día gratis, luego $5 por 1000 |
| Brave Search | $3/mes por 2000 consultas |
| Shodan | $59/mes por el plan básico |

Puedes ejecutar ScannUs con **cero servicios de pago** quedándote con DuckDuckGo + endpoints gratuitos de HIBP + Ollama para IA.

**P: ¿La caché hará que me pierda resultados nuevos?**

Los TTLs por defecto son conservadores:
- 24h para SERPs (los resultados no varían rápido)
- 6h para contenido de páginas
- 1h para DNS

Si sospechas datos obsoletos, `--cache-clear <namespace>` y vuelve a ejecutar. Las capturas de Wayback se cachean 30 días porque son inmutables por diseño.

**P: ¿Puedo ejecutar ScannUs en un contenedor Docker?**

Aún no hay un Dockerfile oficial, pero uno mínimo funciona:

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

**P: ¿Cómo añado un nuevo motor de búsqueda?**

Implementa una clase en `search/engines/` que exponga:

```python
def search(query: str, pages: int, start_page: int, lang: str) -> list[dict]:
    # devolver [{"title": ..., "link": ..., "description": ...}, ...]
```

Regístralo en `cli/actions.py:get_search_engine()` y en `cli/menus.py:_ENGINE_CHOICES`.

**P: ¿Cómo añado un nuevo proveedor de IA?**

Implementa una clase con `generate(prompt)` + `stream(prompt, render)` en `core/ai_agent.py`. Regístrala en `cli/menus.py:select_ia_agent()`. El proveedor debe:

1. Producir trozos de texto desde `stream()`
2. Devolver la cadena unida desde `generate()`

**P: ¿Cómo añado una nueva herramienta al Planificador de Consultas con IA?**

1. Implementa la función en el módulo apropiado (`analysis/`, `search/`, etc.)
2. Añade una entrada de catálogo en `core/ai_agent.py:TOOL_CATALOG` con `desc` y `args`
3. Escribe una función `_dispatch_<nombre>(args, ia_agent)` que devuelva `{status, summary, data}`
4. Regístrala en `core/ai_agent.py:TOOL_DISPATCH`

Eso es todo — el planificador la auto-descubrirá desde `TOOL_CATALOG`.

**P: ¿Puedo controlar ScannUs por script desde Python?**

Sí:

```python
from analysis.hibp import check_account
from analysis.domain_osint import domain_recon
from analysis.advanced_osint import wayback_fetch_snapshot

# Usa cualquier función de módulo directamente
result = check_account("objetivo@example.com")
recon  = domain_recon("example.com")
snap   = wayback_fetch_snapshot("https://example.com", "2020")
```

Todas las llamadas cacheadas funcionan transparentemente — no necesitas conectar la caché tú mismo.

---

## 19. Glosario

| Término | Definición |
|---|---|
| **CDX** | API de índice de capturas de Internet Archive |
| **CSE** | Producto Custom Search Engine de Google (API SERP de pago) |
| **CT log** | Certificate Transparency log — registro público y append-only de certs TLS emitidos. crt.sh es un frontend. |
| **Deep search** | Modo `--deep` de ScannUs: buscar, luego rastrear cada URL de resultado y extraer PII |
| **DKIM** | DomainKeys Identified Mail — autenticación de email vía claves públicas publicadas en DNS |
| **Dork** | Una consulta de Google usando operadores avanzados (`site:`, `filetype:`, etc.) para encontrar contenido no obvio |
| **EIP-55** | Esquema de checksum mixed-case para direcciones Ethereum |
| **HIBP** | Have I Been Pwned — base de datos de inteligencia de brechas de Troy Hunt |
| **k-anonimato** | Consulta que preserva la privacidad: enviar un prefijo de hash, comparar el sufijo localmente. Usado por Pwned Passwords. |
| **OSINT** | Open-Source Intelligence: recolección de información de fuentes públicas |
| **PEM** | Privacy-Enhanced Mail — formato de texto para claves criptográficas (bloques `-----BEGIN…-----`) |
| **PII** | Personally Identifiable Information (información personalmente identificable) |
| **Plan** | Estrategia de investigación multi-paso producida por el Planificador de Consultas con IA |
| **PWA / SPA** | Single-Page Application — sitio renderizado por JS que el HTTP estático no puede ver |
| **ReAct** | Reasoning + Acting: un patrón de agente LLM que intercala planificación, acción y observación |
| **SAN** | Subject Alternative Name — nombres de host adicionales cubiertos por un cert TLS |
| **SPF / DMARC** | Autenticación de email vía registros DNS TXT |
| **TUI** | Text User Interface (la interfaz interactiva de menús) |
| **WAL** | Write-Ahead Log — modo journal de SQLite que permite lecturas concurrentes |
| **Wayback** | El servicio de capturas de Internet Archive |

---

<div align="center">

**Feliz investigación.**

Para reportes de bugs y solicitudes de funciones, mira el [repositorio de GitHub](https://github.com/kahz12/scannus/issues).

</div>
