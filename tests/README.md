# Tests

Fast, network-free unit tests for ScannUs's pure logic — the PII / secret
extractors, the crypto-address and identifier checksum validators, the SQLite
cache, and the results exporters. No API keys, no live sites, no Selenium.

## Running

From the repo root, install the runtime deps plus the `dev` extra (currently
just `pytest`), then run the suite:

```bash
pip install -e ".[dev]"
pytest
```

`pyproject.toml` sets `pythonpath = .` (under `[tool.pytest.ini_options]`), so
the tests import `core`, `search`, and `utils` directly.

Run a single module or test:

```bash
pytest tests/test_pii_extraction.py
pytest tests/test_cache.py::TestExpiry -q
```

## Layout

| File | Covers |
|---|---|
| `test_pii_extraction.py` | emails (incl. obfuscation), phones, IBAN, cards, CUIT/DNI/RFC/SSN/CPF/SIN, Colombian CC/TI/CE and NIT, IPv4/IPv6/MAC, and the `extract_information` orchestrator |
| `test_redaction.py` | Cards, bank accounts, national IDs and secrets replaced with `[withheld: …]` however they are written, while emails, phones, names and URLs stay readable |
| `test_page_prompts.py` | Website text in the summary, analysis and entity-graph prompts: declared as data, unable to close its block, sensitive values withheld, merged chunks declared as data |
| `test_username_enum.py` | The made-up control handle (same shape, reproducible, none for short handles) and the sites that claim it left out of the menu, the saved report, the planner and the hub |
| `test_email_enum.py` | Holehe run without its broken `--timeout` flag, unchecked services counted rather than read as absent, a run with no answers treated as a failure and not cached, the planner summary |
| `test_secret_extraction.py` | AWS/GitHub/GitLab/Slack/Stripe/Google/Telegram tokens, PEM keys, JWT header validation, BTC/ETH address checksums |
| `test_cache.py` | `SQLiteCache` round-trip, namespace isolation, TTL expiry, purge, clear, stats, disable switch, key building |
| `test_results_parse.py` | JSON/CSV/HTML/Excel exports, extracted values from deep searches, and escaping of untrusted fields |
| `test_imports.py` | Guards the `core.ai_agent` → `core.providers` / `core.planner` split: backward-compatible facade exports and catalog/dispatch parity |
| `test_investigation.py` | The investigation loop with a scripted model: each step sees earlier results, limits, failures, untrusted content, sensitive values, reports and saved cases |
| `test_logging_setup.py` | `setup_logging` file/console handlers, `--debug` level switching, logger namespacing, idempotent reconfiguration |
| `test_presidio_loading.py` | Presidio loads on first use only, once, and a failed model download never stops extraction |
| `test_api_engines.py` | Tavily and Exa: the requests they send, one-response paging, `site:` as a domain filter, usage-limit messages, and which engine takes over when DuckDuckGo blocks |
| `test_media_retry.py` | Which media download failures are retried and which stop at once |
| `test_private_files.py` | The setup wizard keeping saved keys on a blank answer, and `.env`, `outputs/` and new files staying limited to the current user |
| `test_search_engines.py` | Engine selection, the move to Brave when DuckDuckGo blocks, Brave's paging limits, and dork prompts limited to operators both engines share |
| `test_search_exports.py` | What `main()` writes after a search: exports and downloads in deep mode, plain-search format, nothing after a failed search, Presidio values kept |
| `test_tech_scanner.py` | Wappalyzer backend loading, browser headers, stack detection, WebTech report parsing, fallback between backends |
| `test_env_file.py` | Commands that need no key run without a `.env` file, and the setup wizard still works |
| `test_extractor_precision.py` | Lookalike numbers are not reported, real formats still are, plus confidence levels and evidence records |
| `test_evidence.py` | Findings keep their origin, saved cases hold evidence and hub findings, older databases upgrade, loading restores the hub |
| `test_exit_codes.py` | The exit code of each command, and what `--recon --json` writes |
| `test_file_download.py` | PDF metadata extraction, including corrupt files |
| `test_gemini_provider.py` | Gemini model resolution (default, `GEMINI_MODEL`, explicit argument), the model sent to the API, and the provider menu label |
| `test_duckduckgo.py` | Anti-bot captcha detection, empty results left out of the search cache, partial results when a later page is blocked, errors reaching the CLI and the planner |
| `test_feedback_fixes.py` | Regressions for `-i` TUI launch, `--list-cases`/`--delete-case`, hub clearing on load, chunking boundaries, case-insensitive tag escaping, JSON brace parsing, provider system roles/OpenAI fixes, CSV formula neutralization, media downloader collision/subdir/TLS fixes, and lazy startup imports |
| `test_domain_osint.py` | Target normalisation, WHOIS/DNS/crt.sh caching & retries, TLS cert parsing, HTTP security headers, Shodan handling, and `domain_recon` async fan-out |
| `test_hibp_and_phone.py` | HIBP k-anonymity SHA-1 prefix isolation, account/paste/breach caching, offline `phone_osint` intelligence/footprint, and `core.unified` record converters |
| `test_throttle_and_wayback.py` | `TokenBucket`, sync/async retry & `Retry-After` handling, TinEye/Bing/manual reverse-image engines, and Wayback CDX/snapshot/diff |

## Notes

- Checksum tests use canonical real-world vectors (the `GB82WEST...` IBAN, the
  Visa `4111...` card, the Bitcoin genesis address, the EIP-55 reference
  Ethereum address) so they assert *correct* behaviour, not just current output.
- TTL expiry is tested by monkeypatching `core.cache.time.time`, so the suite
  never sleeps.
- Exporter tests redirect `DIR_REPORTS` to a `tmp_path`; nothing is written
  outside the sandbox.
