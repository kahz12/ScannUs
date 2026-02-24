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
    Takes a screenshot of the given URL using Selenium in headless mode.
    
    Args:
        url (str): The URL to capture.
        output_dir (str): Directory where the image will be saved.
    
    Returns:
        str: Path of the generated file or None if it fails.
    """
    # Conditional imports to avoid penalizing load time if not used
    from selenium import webdriver
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.firefox.service import Service
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Generate a safe name based on the domain
    domain = urlparse(url).netloc.replace('.', '_')
    if not domain:
        domain = "unknown_domain"
    output_path = os.path.join(output_dir, f"{domain}_screenshot.png")

    options = Options()
    options.add_argument("--headless")
    
    geckodriver_path = "/data/data/com.termux/files/usr/bin/geckodriver"
    service = Service(executable_path=geckodriver_path) if os.path.exists(geckodriver_path) else None

    driver = None
    try:
        console.print(f"[yellow]Iniciando navegador headless para capturar {url}...[/yellow]")
        if service:
            driver = webdriver.Firefox(options=options, service=service)
        else:
            driver = webdriver.Firefox(options=options)
            
        driver.set_page_load_timeout(30)
        driver.get(url)
        
        # Save screenshot
        driver.save_screenshot(output_path)
        console.print(f"[bold green]Captura de pantalla guardada exitosamente en:[/bold green] {output_path}")
        return output_path

    except Exception as e:
        console.print(f"[bold red]Error al tomar captura de pantalla:[/bold red] {e}")
        return None
    finally:
        if driver:
            driver.quit()

def get_dynamic_text_from_url(url):
    """
    Extracts text from a webpage after rendering JavaScript
    using Headless Selenium, solving the hidden content issue.
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
        console.print(f"[yellow]Iniciando Scraping Profundo en {url}...[/yellow]")
        if service:
            driver = webdriver.Firefox(options=options, service=service)
        else:
            driver = webdriver.Firefox(options=options)
            
        driver.set_page_load_timeout(45)
        driver.get(url)
        
        # Simulate scroll to load lazy elements
        console.print("[cyan]Haciendo scroll para forzar carga de contenido dinámico...[/cyan]")
        last_height = driver.execute_script("return document.body.scrollHeight")
        for _ in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
        
        # Get rendered HTML
        html = driver.page_source
        
        # Manual parsing with BeautifulSoup same as web_analyzer
        soup = BeautifulSoup(html, 'html.parser')
        
        for script_or_style in soup(["script", "style"]):
            script_or_style.decompose()
            
        text = soup.get_text()
        
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        clean_text = '\n'.join(chunk for chunk in chunks if chunk)
        
        return clean_text

    except Exception as e:
        console.print(f"[bold red]Error durante el scraping profundo:[/bold red] {e}")
        return None
    finally:
        if driver:
            driver.quit()


def check_wayback_machine(url):
    """
    Verifies if a URL is archived in the Wayback Machine (Internet Archive).
    
    Args:
        url (str): The URL to query.
    
    Returns:
        dict: Dictionary with the most recent archived URL and date, or None.
    """
    console.print(f"\n[yellow]Consultando Wayback Machine para: {url}[/yellow]")
    # Public API for Wayback Machine availability
    api_url = f"http://archive.org/wayback/available?url={url}"
    
    try:
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        archived_snapshots = data.get("archived_snapshots", {})
        if "closest" in archived_snapshots:
            closest = archived_snapshots["closest"]
            if closest.get("available"):
                archive_url = closest.get("url")
                timestamp = closest.get("timestamp", "")
                
                # Format the timestamp (YYYYMMDDhhmmss) if possible
                formatted_date = timestamp
                if len(timestamp) >= 8:
                    formatted_date = f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]}"
                
                console.print(f"[bold green]¡URL encontrada en Wayback Machine![/bold green]")
                console.print(f"  [cyan]Fecha:[/cyan] {formatted_date}")
                console.print(f"  [cyan]URL de archivo:[/cyan] {archive_url}")
                
                return {
                    "url": archive_url,
                    "date": formatted_date
                }
        
        console.print("[yellow]La URL no tiene copias recientes en Wayback Machine.[/yellow]")
        return None
        
    except requests.exceptions.RequestException as e:
        console.print(f"[bold red]Error al comunicarse con la API de Wayback Machine:[/bold red] {e}")
        return None
