# Standard and third-party library imports
import requests  
from bs4 import BeautifulSoup  
from core.ai_agent import IAAgent, GeminiGenerator  
import time
import os
from pyvis.network import Network
from core.config import DIR_GRAPHS

def get_text_from_url(url):
    """
    Extracts and cleans the text content of a webpage.

    Downloads the HTML of a URL, parses it via BeautifulSoup,
    and strips out non-visible DOM elements (like scripts and styles) to isolate
    the human-readable text payload.

    Args:
        url (str): The target web address.

    Returns:
        str: Sanitized webpage text, or None if extraction fails.
    """
    try:
        # User-Agent spoofing to bypass rudimentary anti-bot mechanisms.
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        # Execute HTTP GET with a 15s timeout buffer.
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Prune non-content DOM nodes.
        for script_or_style in soup(["script", "style"]):
            script_or_style.decompose() 
            
        text = soup.get_text()
        
        # Text normalization pipeline:
        # 1. Strip trailing/leading whitespace per line.
        lines = (line.strip() for line in text.splitlines())
        # 2. Break apart lines by multiple spaces to catch inline gaps.
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        # 3. Join valid chunks with line breaks for clean ingestion.
        clean_text = '\n'.join(chunk for chunk in chunks if chunk)
        
        return clean_text
    except requests.exceptions.RequestException as e:
        print(f"Error extracting text from {url}: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error during URL processing: {e}")
        return None

def _build_summary_prompt(text):
    """
    Constructs the base prompt for LLM summarization tasks.
    """
    return f"Please provide a concise and technical summary of the following text extracted from a webpage:\n\n---\n{text}\n---"

def summarize_text_with_ia(text, ia_agent):
    """
    Delegates text summarization to the active AI Agent.

    Args:
        text (str): The raw text payload.
        ia_agent (IAAgent): The active AI worker instance.

    Returns:
        str: AI-generated summary or error diagnostic.
    """
    if not text:
        return "No text provided for summarization."

    # Prevent token limit overflow (approx 30k chars safety limit).
    max_chars = 30000 
    if len(text) > max_chars:
        text = text[:max_chars] + "... [Text truncated due to length constraints]"

    try:
        prompt = _build_summary_prompt(text)
        summary = ia_agent.generator.generate(prompt)
        return summary if summary else "AI failed to generate a summary."
    except Exception as e:
        return f"AI Generation Error: {e}"

def _build_translation_analysis_prompt(text):
    """
    Constructs the base prompt for deep context analysis and key insight extraction.
    """
    return f'''
        Act as an expert OSINT analyst. Analyze the following extracted text from a website
        and provide a detailed technical summary of its content. 
        Highlight key entities, potential leads, and core topics.
        The text may contain extraction noise; infer context where necessary.

        TEXT:
        {text}
        '''

def translate_and_analyze_with_ia(text, ia_agent):
    """
    Performs context analysis using the AI agent.
    
    Args:
        text (str): The target raw text.
        ia_agent (IAAgent): The active AI worker instance.
        
    Returns:
        str: The AI's analytical response payload.
    """
    if not text:
        return "No text provided for analysis."

    # Enforce token limit safety buffer.
    max_chars = 30000 
    if len(text) > max_chars:
        text = text[:max_chars] + "... [Text truncated]"

    try:
        prompt = _build_translation_analysis_prompt(text)
        analysis_result = ia_agent.generator.generate(prompt)
        return analysis_result if analysis_result else "AI failed to generate analysis."
    except Exception as e:
        return f"AI Generation Error: {e}"

def extract_entities_and_graph(text, ia_agent, output_filename="graph.html"):
    """
    Orchestrates AI-driven entity extraction and relationship mapping,
    rendering an interactive HTML graph using Pyvis.
    
    Args:
        text (str): Source text payload.
        ia_agent (IAAgent): AI Agent for entity extraction.
        output_filename (str): Name of the generated HTML artifact.
        
    Returns:
        str: Absolute path to the generated HTML graph, or None on failure.
    """
    output_filename = os.path.join(DIR_GRAPHS, os.path.basename(output_filename))
    if not text:
        print("[bold red]No text available for graph analysis.[/bold red]")
        return None

    # Stricter character limit for complex reasoning tasks.
    max_chars = 25000 
    if len(text) > max_chars:
        text = text[:max_chars] + "... [Text truncated]"

    # Few-shot prompt enforcing exact pipe-delimited schema for reliable parsing.
    prompt = f'''
    Act as an OSINT Intelligence Analyst. Read the following text and extract relationships between distinct entities.
    Entities can be: Person, Organization, Location, Website/Domain, Email, or Technology.
    
    Return ONLY a list of relationships in plain text using the following schema (one per line):
    [Entity 1] | [Type of Entity 1] | [Relationship description] | [Entity 2] | [Type of Entity 2]
    
    Example:
    John Doe | Person | works at | Tech Corp | Organization
    Tech Corp | Organization | located in | New York | Location
    admin@example.com | Email | belongs to | John Doe | Person
    
    Do NOT use Markdown. Do NOT include any preamble or postamble.
    If no relationships are found, respond with "NO_RELATIONSHIPS".
    
    Source Text:
    {text}
    '''

    try:
        response_text = ia_agent.generator.generate(prompt)
        if not response_text or response_text.strip() == "NO_RELATIONSHIPS":
            print("[yellow]No sufficient entities or relationships identified for graph generation.[/yellow]")
            return None
            
        # Bootstrap Pyvis Network with a dark-themed TUI aesthetic.
        net = Network(height="750px", width="100%", bgcolor="#222222", font_color="white", directed=True)
        
        # Color palette for entity classifications.
        color_map = {
            'Person': '#E57373',
            'Organization': '#64B5F6',
            'Location': '#81C784',
            'Website': '#FFD54F', 'Domain': '#FFD54F',
            'Email': '#BA68C8',
            'Technology': '#4DB6AC'
        }
        
        lines = response_text.strip().split('\n')
        nodes_added = set()
        edges_added = 0
        
        # Parse the structured LLM output.
        for line in lines:
            parts = [p.strip() for p in line.split('|')]
            
            # Discard malformed lines to maintain graph integrity.
            if len(parts) == 5:
                e1, t1, relation, e2, t2 = parts
                
                # Default to white for unmapped types.
                c1 = color_map.get(t1, "#FFFFFF")
                c2 = color_map.get(t2, "#FFFFFF")
                
                # Check cache to prevent duplicate node exceptions.
                if e1 not in nodes_added:
                    net.add_node(e1, label=e1, title=t1, color=c1)
                    nodes_added.add(e1)
                
                if e2 not in nodes_added:
                    net.add_node(e2, label=e2, title=t2, color=c2)
                    nodes_added.add(e2)
                
                # Establish directed edge.
                net.add_edge(e1, e2, title=relation, label=relation, color="#aaaaaa")
                edges_added += 1

        if edges_added == 0:
            print("[yellow]No valid relationships parsed to build the graph.[/yellow]")
            return None

        net.save_graph(output_filename)
        print(f"[green]Graph successfully generated and saved to:[/green] {output_filename}")
        return output_filename

    except Exception as e:
        print(f"[bold red]Graph generation failure:[/bold red] {e}")
        return None

# --- Standalone Smokescreen Test ---
if __name__ == '__main__':
    """
    Demonstration block for unit testing the module's extraction and AI pipeline.
    """
    test_url = "https://www.xataka.com/robotica-e-ia/gemini-1-5-pro-probamos-brutal-ia-google-que-analiza-documentos-videos-codigo-da-sopas-chatgpt-4"
    
    print(f"--- Fetching text from: {test_url} ---")
    page_text = get_text_from_url(test_url)
    
    if page_text:
        print("\n--- Extracted Text Preview (500 chars) ---")
        print(page_text[:500])
        
        print("\n--- Triggering AI Summarization (Gemini) ---")
        try:
            from dotenv import load_dotenv
            import os

            load_dotenv() 
            gemini_key = os.getenv("GOOGLE_API_KEY_FOR_GEMINI")
            
            if gemini_key:
                gemini_gen = GeminiGenerator()
                agent = IAAgent(gemini_gen)
                
                summary = summarize_text_with_ia(page_text, agent)
                print("\n--- Summary Output ---")
                print(summary)
            else:
                print("\nWarning: GOOGLE_API_KEY_FOR_GEMINI not found in .env.")

        except ImportError:
            print("\nWarning: Missing dependencies for local testing (python-dotenv).")
        except Exception as e:
            print(f"\nExample execution failure: {e}")
