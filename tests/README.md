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
| `test_pii_extraction.py` | emails (incl. obfuscation), phones, IBAN, cards, CUIT/DNI/RFC/SSN/CPF/SIN, IPv4/IPv6/MAC, and the `extract_information` orchestrator |
| `test_secret_extraction.py` | AWS/GitHub/GitLab/Slack/Stripe/Google/Telegram tokens, PEM keys, JWT header validation, BTC/ETH address checksums |
| `test_cache.py` | `SQLiteCache` round-trip, namespace isolation, TTL expiry, purge, clear, stats, disable switch, key building |
| `test_results_parse.py` | JSON/CSV/HTML/Excel exports and HTML-escaping of untrusted fields |
| `test_imports.py` | Guards the `core.ai_agent` → `core.providers` / `core.planner` split: backward-compatible facade exports and catalog/dispatch parity |
| `test_logging_setup.py` | `setup_logging` file/console handlers, `--debug` level switching, logger namespacing, idempotent reconfiguration |

## Notes

- Checksum tests use canonical real-world vectors (the `GB82WEST...` IBAN, the
  Visa `4111...` card, the Bitcoin genesis address, the EIP-55 reference
  Ethereum address) so they assert *correct* behaviour, not just current output.
- TTL expiry is tested by monkeypatching `core.cache.time.time`, so the suite
  never sleeps.
- Exporter tests redirect `DIR_REPORTS` to a `tmp_path`; nothing is written
  outside the sandbox.
