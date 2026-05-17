"""
analysis/web_analyzer.py — Web content extraction and AI-driven analysis.

Key improvements:
  - Replaced all plain print() with Rich console helpers
  - Text chunking instead of hard truncation: long texts are summarised in
    overlapping chunks and the partial summaries are merged for a final answer
"""

import os
import requests
from bs4 import BeautifulSoup
from pyvis.network import Network

from core.config import DIR_GRAPHS
from cli.ui import print_info, print_warn, print_error


# ---------------------------------------------------------------------------
# Web text extraction
# ---------------------------------------------------------------------------

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en;q=0.9, es;q=0.8",
}

# Optional dependencies — imported lazily so the module still works without them.
try:
    import trafilatura  # type: ignore
    _HAS_TRAFILATURA = True
except Exception:
    _HAS_TRAFILATURA = False

try:
    from readability import Document  # readability-lxml
    _HAS_READABILITY = True
except Exception:
    _HAS_READABILITY = False


def _soup_fallback(html: str) -> str:
    """Last-resort extraction when no readability library is available."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside", "form"]):
        tag.decompose()
    raw = soup.get_text(separator="\n")
    lines = (line.strip() for line in raw.splitlines())
    return "\n".join(line for line in lines if line)


def _fetch_and_clean(url: str) -> str | None:
    """Uncached implementation of :func:`get_text_from_url`."""
    try:
        response = requests.get(url, headers=_HEADERS, timeout=15, allow_redirects=True)
        response.raise_for_status()

        # Validate Content-Type: only parse HTML/XHTML
        ctype = response.headers.get("content-type", "").lower()
        if ctype and not any(t in ctype for t in ("text/html", "application/xhtml", "text/plain", "application/xml")):
            print_warn(f"Skipping non-HTML content ({ctype.split(';')[0]}) at {url}")
            return None

        html = response.text
        if not html.strip():
            return None

        # Tier 1 — trafilatura
        if _HAS_TRAFILATURA:
            extracted = trafilatura.extract(
                html, url=url,
                favor_recall=True,
                include_comments=False,
                include_tables=True,
                no_fallback=False,
            )
            if extracted and len(extracted) > 80:
                return extracted

        # Tier 2 — readability-lxml (article body, then clean text)
        if _HAS_READABILITY:
            try:
                doc = Document(html)
                summary_html = doc.summary(html_partial=True)
                text = _soup_fallback(summary_html)
                if text and len(text) > 80:
                    return text
            except Exception:
                pass

        # Tier 3 — BeautifulSoup fallback
        return _soup_fallback(html) or None

    except requests.exceptions.RequestException as e:
        print_error(f"Network error fetching {url}: {e}")
        return None
    except Exception as e:
        print_error(f"Unexpected error processing {url}: {e}")
        return None


def get_text_from_url(url: str) -> str | None:
    """
    Cached wrapper for the URL text extractor.

    On a cache hit, returns the previously-extracted text without hitting
    the network. The first call for a given URL pays the full extraction
    cost (trafilatura -> readability -> BeautifulSoup fallback chain) and
    persists the result under the ``http_text`` namespace (default TTL: 6h).
    """
    from core.cache import cached_call
    return cached_call("http_text", [url], lambda: _fetch_and_clean(url))


# ---------------------------------------------------------------------------
# Text chunking utilities
# ---------------------------------------------------------------------------

_CHUNK_SIZE   = 12_000   # characters per chunk sent to the LLM
_CHUNK_OVERLAP = 500     # overlap to preserve context at boundaries


def _split_into_chunks(text: str, chunk_size: int = _CHUNK_SIZE,
                       overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """
    Splits a long text into overlapping fixed-size character chunks.

    Args:
        text:       Source text.
        chunk_size: Maximum characters per chunk.
        overlap:    Characters of overlap between consecutive chunks.

    Returns:
        List of text chunk strings.
    """
    chunks, start = [], 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


def _chunk_generate(text: str, build_prompt_fn, ia_agent,
                    merge_prompt: str | None = None) -> str:
    """
    Handles LLM calls for long texts by splitting into chunks.

    Strategy:
      1. If text fits in one chunk → single call.
      2. If text is too long → process each chunk independently, then ask
         the LLM to merge the partial answers into a single final response.

    Args:
        text:            Source text.
        build_prompt_fn: Callable(chunk_text) → prompt string.
        ia_agent:        Active IAAgent instance.
        merge_prompt:    Optional template for the merging step.
                         Should contain a `{partials}` placeholder.

    Returns:
        Final generated text string.
    """
    chunks = _split_into_chunks(text)

    if len(chunks) == 1:
        return ia_agent.generator.generate(build_prompt_fn(chunks[0]))

    print_info(f"Text is long ({len(text):,} chars) — processing in {len(chunks)} chunks…")

    partials = []
    for i, chunk in enumerate(chunks, 1):
        print_info(f"  Processing chunk {i}/{len(chunks)}…")
        result = ia_agent.generator.generate(build_prompt_fn(chunk))
        partials.append(result)

    if merge_prompt is None:
        merge_prompt = (
            "You received partial analyses of different sections of the same document. "
            "Merge them into a single, coherent, non-redundant summary:\n\n{partials}"
        )

    merged_input = merge_prompt.format(partials="\n\n---\n\n".join(partials))
    print_info("  Merging partial results…")
    return ia_agent.generator.generate(merged_input)


# ---------------------------------------------------------------------------
# AI-powered functions
# ---------------------------------------------------------------------------

def _build_summary_prompt(text: str) -> str:
    return (
        "Please provide a concise and technical summary of the following text "
        "extracted from a webpage:\n\n---\n" + text + "\n---"
    )


def summarize_text_with_ia(text: str, ia_agent) -> str:
    """
    Summarises webpage text using the active AI agent.
    Automatically chunks the text if it exceeds the token-safe limit.

    Args:
        text:     Raw text payload.
        ia_agent: Active IAAgent instance.

    Returns:
        AI-generated summary string.
    """
    if not text:
        return "No text provided for summarisation."
    try:
        return _chunk_generate(text, _build_summary_prompt, ia_agent)
    except Exception as e:
        return f"AI Generation Error: {e}"


def _build_analysis_prompt(text: str) -> str:
    return (
        "Act as an expert OSINT analyst. Analyse the following extracted text from a "
        "website and provide a detailed technical summary. Highlight key entities, "
        "potential leads, and core topics. The text may contain extraction noise; "
        "infer context where necessary.\n\nTEXT:\n" + text
    )


def translate_and_analyze_with_ia(text: str, ia_agent) -> str:
    """
    Performs deep OSINT-focused analysis using the AI agent.
    Supports chunked processing for long texts.

    Args:
        text:     Raw text payload.
        ia_agent: Active IAAgent instance.

    Returns:
        AI analytical response.
    """
    if not text:
        return "No text provided for analysis."
    try:
        return _chunk_generate(
            text,
            _build_analysis_prompt,
            ia_agent,
            merge_prompt=(
                "You are an OSINT analyst. You received partial analyses of different "
                "sections of the same webpage. Merge them into one coherent report, "
                "removing duplicate information and keeping the most relevant findings:\n\n"
                "{partials}"
            ),
        )
    except Exception as e:
        return f"AI Generation Error: {e}"


# ---------------------------------------------------------------------------
# Entity graph
# ---------------------------------------------------------------------------

def extract_entities_and_graph(text: str, ia_agent,
                               output_filename: str = "graph.html") -> str | None:
    """
    Extracts entity relationships via AI and renders an interactive Pyvis graph.

    Supports chunked input: extracts relationships per chunk, deduplicates,
    then builds the graph from the full merged edge list.

    Args:
        text:            Source text payload.
        ia_agent:        Active IAAgent instance.
        output_filename: Name of the output HTML graph file.

    Returns:
        Absolute path to the HTML graph, or None on failure.
    """
    output_path = os.path.join(DIR_GRAPHS, os.path.basename(output_filename))

    if not text:
        print_error("No text available for graph analysis.")
        return None

    _ENTITY_PROMPT = lambda t: f"""
Act as an OSINT Intelligence Analyst. Read the text and extract relationships between entities.
Entities: Person, Organization, Location, Website/Domain, Email, Technology.

Return ONLY a list of relationships (one per line) in this exact schema:
[Entity 1] | [Type 1] | [Relationship] | [Entity 2] | [Type 2]

Example:
John Doe | Person | works at | Tech Corp | Organization

Do NOT use Markdown. Do NOT add any preamble.
If no relationships, respond with NO_RELATIONSHIPS.

Source Text:
{t}
"""

    try:
        raw = _chunk_generate(text, _ENTITY_PROMPT, ia_agent,
                              merge_prompt=(
                                  "Below are relationship lists extracted from multiple chunks "
                                  "of the same document. Merge them into one deduplicated list "
                                  "using the same pipe-delimited schema. Output ONLY the list:\n\n"
                                  "{partials}"
                              ))

        if not raw or raw.strip() == "NO_RELATIONSHIPS":
            print_warn("No sufficient entities found for graph generation.")
            return None

        color_map = {
            "Person": "#E57373", "Organization": "#64B5F6", "Location": "#81C784",
            "Website": "#FFD54F", "Domain": "#FFD54F",
            "Email": "#BA68C8", "Technology": "#4DB6AC",
        }

        net = Network(height="750px", width="100%",
                      bgcolor="#1a1a2e", font_color="white", directed=True)
        net.set_options("""{"physics": {"stabilization": {"iterations": 150}}}""")

        nodes_added: set = set()
        edges_added = 0

        for line in raw.strip().splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) != 5:
                continue
            e1, t1, relation, e2, t2 = parts
            for entity, etype in ((e1, t1), (e2, t2)):
                if entity not in nodes_added:
                    net.add_node(entity, label=entity, title=etype,
                                 color=color_map.get(etype, "#FFFFFF"),
                                 size=20, font={"size": 12})
                    nodes_added.add(entity)
            net.add_edge(e1, e2, title=relation, label=relation, color="#888888")
            edges_added += 1

        if edges_added == 0:
            print_warn("No valid relationships parsed for graph building.")
            return None

        net.save_graph(output_path)
        print_info(f"Entity graph saved → {output_path}")
        return output_path

    except Exception as e:
        print_error(f"Graph generation failure: {e}")
        return None
