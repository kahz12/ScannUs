import sys
import os

from core.config import load_environment, env_config, openai_config, init_directories
from core.logging_setup import setup_logging, get_logger
from cli.ui import console, print_startup_banner
from cli.parser import get_parser, show_custom_help
from cli.menus import show_main_menu, select_ia_agent
from search.reverse_image import do_reverse_image_search
from core.case_manager import load_case
from utils.file_download import FileDownload
from utils.media_downloader import download_media
from utils.results_parse import ResultsParser
from core import state

def main():
    """
    Main entry point for the ScannUs application.
    Bootstraps the environment, parses CLI arguments, and dispatches to the correct module.
    """
    # Initialize workspace scaffold and required directory structure
    init_directories()

    # Configure logging before anything else does real work. We read --debug
    # straight from argv here because it must be live for both the CLI path
    # (parsed below) and the interactive TUI path (which never reaches parse).
    setup_logging(debug="--debug" in sys.argv)
    log = get_logger(__name__)
    log.info("ScannUs starting (argv=%s)", sys.argv[1:])

    # Load environment variables (API keys, etc.) and verify core requirements
    google_api_key_found = load_environment()
    print_startup_banner(bool(google_api_key_found))
    
    parser = get_parser()

    # Intercept custom help flag to render the rich-formatted help screen
    if '-h' in sys.argv or '--help' in sys.argv:
        show_custom_help(parser)
        sys.exit(0)
    
    # Drop into interactive TUI if no command-line arguments are provided
    if len(sys.argv) == 1:
        show_main_menu()
        sys.exit(0)

    args = parser.parse_args()

    # --- Configuration Verification & Setup ---
    env_exists = os.path.exists(".env")
    if args.configure:
        print("Initializing environment configuration...")
        env_config()
        openai_config()
        print("\n.env configured successfully.")
        # Exit gracefully if -c was the only flag passed
        if all(a in ("-c", "--configure") for a in sys.argv[1:]):
            sys.exit(0)
    elif not env_exists and not args.help:
        console.print("[bold red]Error: The .env file does not exist or is not configured.[/bold red]")
        console.print("Please run the script with the -c flag or use the interactive menu to configure it.")
        sys.exit(1)

    # Route: Cache management
    if getattr(args, "cache_stats", False):
        from core.cache import get_cache
        stats = get_cache().stats()
        console.print("  [bold]Cache stats[/bold]")
        for k, v in stats.items():
            console.print(f"    {k}: {v}")
        sys.exit(0)
    if getattr(args, "cache_clear", None):
        from core.cache import get_cache
        ns = None if args.cache_clear == "__ALL__" else args.cache_clear
        n = get_cache().clear(ns)
        label = "everything" if ns is None else f"namespace '{ns}'"
        console.print(f"  Cleared {label}: {n} row(s) removed.")
        sys.exit(0)

    # Route: HIBP breach & leak checks
    # Each of the four --hibp-* flags maps to a specific analysis.hibp function.
    # They're checked in order of "most likely to be useful first": account is the
    # richest query, domain is the free overview, breach drills into one event,
    # and password is the interactive k-anon check.

    if getattr(args, "hibp_account", None):
        # --hibp-account EMAIL: fetch + render breaches and pastes for an email.
        # check_account() calls hibp_breached_account + hibp_pastes_for_account
        # and renders both tables in one shot. Needs HIBP_API_KEY.
        from analysis.hibp import check_account
        check_account(args.hibp_account)
        sys.exit(0)

    if getattr(args, "hibp_domain", None):
        # --hibp-domain DOMAIN: free endpoint, no API key needed.
        # Good for a quick "has this company been breached?" check.
        from analysis.hibp import check_domain
        check_domain(args.hibp_domain)
        sys.exit(0)

    if getattr(args, "hibp_breach", None):
        # --hibp-breach NAME: dump full metadata for a single named breach.
        # The breach "Name" is HIBP's internal ID (usually the company name).
        # We render it inline here rather than delegating to a renderer
        # because the CLI wants a simple key:value display, not a Rich table.
        from analysis.hibp import hibp_breach
        info = hibp_breach(args.hibp_breach)
        if not info:
            console.print(f"[bold red]No record for breach '{args.hibp_breach}'.[/bold red]")
        else:
            console.print(
                f"\n[bold]{info.get('Name')}[/bold]  ({info.get('BreachDate')})"
            )
            console.print(f"  domain      : {info.get('Domain')}")
            console.print(f"  accounts    : {info.get('PwnCount', 0):,}")
            console.print(f"  data classes: {', '.join(info.get('DataClasses') or [])}")
            console.print(f"  verified    : {info.get('IsVerified')}")
            desc = (info.get('Description') or '').strip()
            if desc:
                console.print(f"\n{desc}\n")
        sys.exit(0)

    if getattr(args, "hibp_password", False):
        # --hibp-password: interactive hidden prompt + k-anonymity check.
        # We use getpass (which suppresses echo) so the password never appears
        # on screen, in shell history, or in process listings (/proc/cmdline).
        # The plaintext also never hits the network — see analysis/hibp.py for
        # the k-anon design details.
        import getpass
        from analysis.hibp import check_password
        try:
            pw = getpass.getpass("  Password (hidden): ")
        except (KeyboardInterrupt, EOFError):
            # User hit Ctrl+C or Ctrl+D — exit cleanly, no stack trace.
            console.print("\n[yellow]Cancelled.[/yellow]")
            sys.exit(1)
        if not pw:
            console.print("[bold red]Password cannot be empty.[/bold red]")
            sys.exit(1)
        check_password(pw)
        sys.exit(0)

    # Route: Reverse Image Search payload processing
    if args.reverse:
        do_reverse_image_search(args.reverse)
        sys.exit(0)

    # Route: Domain / network OSINT recon
    if getattr(args, "recon", None):
        from analysis.domain_osint import domain_recon
        domain_recon(args.recon)
        sys.exit(0)

    # Route: Username enumeration via Sherlock / Maigret (400+ sites)
    if getattr(args, "username_enum", None):
        from search.username_enum import username_enum
        username_enum(args.username_enum,
                      backend=getattr(args, "enum_backend", "auto"))
        sys.exit(0)

    # Route: Email enumeration via Holehe (~120 services)
    if getattr(args, "email_enum", None):
        from search.email_enum import email_enum
        email_enum(args.email_enum,
                   only_used=not getattr(args, "email_enum_all", False))
        sys.exit(0)

    # Route: Phone intelligence via libphonenumber (offline metadata + footprint)
    if getattr(args, "phone_osint", None):
        from search.phone_osint import phone_osint
        phone_osint(args.phone_osint)
        sys.exit(0)

    # Route: LLM-based query planner (multi-step ReAct investigation)
    if getattr(args, "plan", None):
        from cli.actions import do_query_planner
        do_query_planner(args.plan)
        sys.exit(0)

    # Route: Media scraping from a target URL
    if args.media_scrape:
        zip_file_name = "downloaded_media.zip"
        download_media(args.media_scrape, zip_file_name)
        sys.exit(0)

    # Lazily initialize AI agent only if explicitly requested for NLP tasks
    ia_agent = None
    if args.google_dorks or args.interactive or args.load_case:
        ia_agent = select_ia_agent()
        if not ia_agent and (args.google_dorks or args.interactive or args.load_case):
            console.print("[bold red]An AI agent is required for this action, but initialization failed.[/bold red]")
            sys.exit(1)

    # Route: Reload serialized state from previous investigations
    if args.load_case:
        if load_case():
            from cli.menus import interactive_analysis_menu
            interactive_analysis_menu(state.LAST_RESULTS, ia_agent)
        sys.exit(0)
        
    # Route: LLM-based Google Dork generation
    if args.google_dorks:
        console.print(f"Generating dork for description: '{args.google_dorks}'", style="yellow")
        dork_generado = ia_agent.generate_gdork(args.google_dorks)
        if dork_generado:
            console.print("\n✅ Dork Generated:", style="bold green")
            console.print(dork_generado.strip())
        else:
            console.print("\n❌ Failed to generate the dork.", style="bold red")
        sys.exit(0)

    # Build the final search query string based on provided flags
    query = args.query
    if not query:
        guided_parts = []
        if args.name:     guided_parts.append(f'"{args.name}"')
        if args.username: guided_parts.append(f'"{args.username}"')
        if args.email:    guided_parts.append(f'"{args.email}"')
        if args.phone:    guided_parts.append(f'"{args.phone}"')
        if args.search:   guided_parts.append(f'"{args.search}"')
        
        # Aggregate parameters into a logical AND query
        if guided_parts:
            query = " AND ".join(guided_parts)

    # Validate that at least one search parameter or query is present
    if not query:
        console.print("[bold red]Error: You must provide a query via -q or use guided search arguments (-n, -u, -b, -e, -t).[/bold red]")
        sys.exit(1)

    # Latent imports to avoid circular dependency cycles
    from cli.actions import do_search, do_deep_search

    # Dispatch to appropriate search engine or deep analysis pipeline
    if args.deep or args.email or args.phone:
        do_deep_search(query, args.engine, args.pages, args.start_page, args.lang)
    else:
        do_search(query, args.engine, args.pages, args.start_page, args.lang, args.interactive, ia_agent)

    # Post-processing and export logic (active only if not in interactive mode)
    if not args.interactive and not (args.deep or args.email or args.phone):
        results = state.LAST_RESULTS
        rparser = ResultsParser(results)

        # Batch export results to requested formats
        if args.html: rparser.export_html(args.html)
        if args.json: rparser.export_json(args.json)
        if args.csv: rparser.export_csv(args.csv)
        if args.excel: rparser.export_excel(args.excel)

        # Execute automated file downloads and metadata extraction
        if args.download:
            file_types = [ft.strip() for ft in args.download.split(',')]
            urls = [r['link'] for r in results]
            fdownloader = FileDownload("Downloads")
            for url in urls:
                # Filter by file extension or process all if 'all' wildcard is used
                if any(url.lower().endswith(f".{file_type}") for file_type in file_types) or "all" in file_types:
                    fdownloader.download_file(url, args.metadata)

if __name__ == "__main__":
    main()
