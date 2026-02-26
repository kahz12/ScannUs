import os
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from rich.console import Console
from core.config import DIR_SCREENSHOTS

console = Console()

def take_screenshot(url, output_dir=DIR_SCREENSHOTS):
    """
    Captures a high-resolution screenshot of the target URL using Headless Selenium.
    
    Args:
        url (str): The target URL to capture.
        output_dir (str): Destination directory for the resulting image.
    
    Returns:
        str: Absolute path to the generated PNG artifact, or None on failure.
    """
    # Latent imports to minimize interpreter startup overhead
    from selenium import webdriver
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.firefox.service import Service
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Sanitize the domain string to create a filesystem-safe filename
    domain = urlparse(url).netloc.replace('.', '_')
    if not domain:
        domain = "unknown_domain"
    output_path = os.path.join(output_dir, f"{domain}_screenshot.png")

    options = Options()
    options.add_argument("--headless")
    
    # Geckodriver path specifically mapped for Termux environments
    geckodriver_path = "/data/data/com.termux/files/usr/bin/geckodriver"
    service = Service(executable_path=geckodriver_path) if os.path.exists(geckodriver_path) else None

    driver = None
    try:
        console.print(f"[yellow]Starting headless browser to capture {url}...[/yellow]")
        if service:
            driver = webdriver.Firefox(options=options, service=service)
        else:
            driver = webdriver.Firefox(options=options)
            
        driver.set_page_load_timeout(30)
        driver.get(url)
        
        # Flush the frame buffer to the local disk as a PNG
        driver.save_screenshot(output_path)
        console.print(f"[bold green]Screenshot successfully saved to:[/bold green] {output_path}")
        return output_path

    except Exception as e:
        console.print(f"[bold red]Error capturing screenshot:[/bold red] {e}")
        return None
    finally:
        # Mandatory process group teardown to prevent zombie browser instances
        if driver:
            driver.quit()

def get_dynamic_text_from_url(url):
    """
    Extracts text payload from a webpage after executing JavaScript via Headless Selenium.
    Essential for SPAs (Single Page Applications) or content hidden behind lazy-loaders.
    """
    from selenium import webdriver
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.firefox.service import Service
    
    options = Options()
    options.add_argument("--headless")
    
    geckodriver_path = "/data/data/com.termux/files/usr/bin/geckodriver"
    service = Service(executable_path=geckodriver_path) if os.path.exists(geckodriver_path) else None

    driver = None
    try:
        console.print(f"[yellow]Starting Deep Scraping on {url}...[/yellow]")
        if service:
            driver = webdriver.Firefox(options=options, service=service)
        else:
            driver = webdriver.Firefox(options=options)
            
        driver.set_page_load_timeout(45)
        driver.get(url)
        
        # Dispatch synthetic scroll events to trigger dynamic content hydration
        console.print("[cyan]Scrolling to force dynamic content load...[/cyan]")
        last_height = driver.execute_script("return document.body.scrollHeight")
        for _ in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            new_height = driver.execute_script("return document.body.scrollHeight")
            # Break early if the DOM height stabilizes
            if new_height == last_height:
                break
            last_height = new_height
        
        # Retrieve the fully mutated DOM source
        html = driver.page_source
        
        # Leverage BeautifulSoup to strip non-textual nodes
        soup = BeautifulSoup(html, 'html.parser')
        
        for script_or_style in soup(["script", "style"]):
            script_or_style.decompose()
            
        text = soup.get_text()
        
        # Clean and normalize the text payload
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        clean_text = '\n'.join(chunk for chunk in chunks if chunk)
        
        return clean_text

    except Exception as e:
        console.print(f"[bold red]Error during deep scraping:[/bold red] {e}")
        return None
    finally:
        if driver:
            driver.quit()


def check_wayback_machine(url):
    """
    Queries the Internet Archive Availability API to check for historical snapshots of the target URL.
    
    Args:
        url (str): The target URL to query.
    
    Returns:
        dict: Snapshot metadata (URL and timestamp) if found, otherwise None.
    """
    console.print(f"\n[yellow]Querying Wayback Machine for: {url}[/yellow]")
    # Interface with the Wayback Machine Availability API
    api_url = f"http://archive.org/wayback/available?url={url}"
    
    try:
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Traverse the JSON schema for the 'closest' available snapshot
        archived_snapshots = data.get("archived_snapshots", {})
        if "closest" in archived_snapshots:
            closest = archived_snapshots["closest"]
            if closest.get("available"):
                archive_url = closest.get("url")
                timestamp = closest.get("timestamp", "")
                
                # Normalize raw timestamp (YYYYMMDDhhmmss) to YYYY-MM-DD
                formatted_date = timestamp
                if len(timestamp) >= 8:
                    formatted_date = f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]}"
                
                console.print(f"[bold green]URL found in Wayback Machine![/bold green]")
                console.print(f"  [cyan]Date:[/cyan] {formatted_date}")
                console.print(f"  [cyan]Archive URL:[/cyan] {archive_url}")
                
                return {
                    "url": archive_url,
                    "date": formatted_date
                }
        
        console.print("[yellow]The URL has no recent snapshots in the Wayback Machine.[/yellow]")
        return None
        
    except requests.exceptions.RequestException as e:
        console.print(f"[bold red]Error communicating with the Wayback Machine API:[/bold red] {e}")
        return None
