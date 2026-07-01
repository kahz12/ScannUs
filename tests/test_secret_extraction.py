"""
Unit tests for leaked-token / secret / crypto-address detection in
``search.smart_search``.

These detectors are deliberately prefix-anchored to keep false positives low,
so the tests exercise both the "clearly a real token" path and the
"looks similar but must be rejected" path (e.g. a JWT-shaped string whose
header is not valid JSON, a mixed-case Ethereum address failing EIP-55).
"""

import base64
import json

from search import smart_search as s


# ---------------------------------------------------------------------------
# Provider API keys / tokens
# ---------------------------------------------------------------------------

class TestSecretPatterns:
    def test_aws_access_keys(self):
        out = s._extract_secrets("key AKIAIOSFODNN7EXAMPLE and ASIAABCDEFGHIJKLMNOP")
        assert out["aws_access_keys"] == {
            "AKIAIOSFODNN7EXAMPLE",
            "ASIAABCDEFGHIJKLMNOP",
        }

    def test_github_classic_and_fine_grained(self):
        classic = "ghp_" + "a" * 36
        fine = "github_pat_" + "b" * 82
        out = s._extract_secrets(f"{classic} then {fine}")
        assert out["github_tokens"] == {classic, fine}

    def test_gitlab_token(self):
        tok = "glpat-" + "A1b2C3d4E5f6G7h8I9j0"
        assert s._extract_secrets(f"x {tok} y")["gitlab_tokens"] == {tok}

    def test_slack_token(self):
        tok = "xoxb-" + "1234567890" + "-abcdEFGH"
        assert s._extract_secrets(f"x {tok} y")["slack_tokens"] == {tok}

    def test_stripe_secret_key(self):
        tok = "sk_live_" + "a" * 24
        assert s._extract_secrets(f"x {tok} y")["stripe_keys"] == {tok}

    def test_google_api_key_exact_length(self):
        key = "AIza" + "0" * 35  # 39 chars total
        assert s._extract_secrets(f"x {key} y")["google_api_keys"] == {key}

    def test_google_api_key_wrong_length_rejected(self):
        # One extra trailing char breaks the word boundary -> no match
        key = "AIza" + "0" * 36
        assert "google_api_keys" not in s._extract_secrets(f"x {key} y")

    def test_telegram_bot_token(self):
        tok = "123456789:" + "A" * 35
        assert s._extract_secrets(f"x {tok} y")["telegram_tokens"] == {tok}

    def test_private_key_pem_header(self):
        pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIB...\n-----END RSA PRIVATE KEY-----"
        out = s._extract_secrets(pem)
        assert "private_keys" in out

    def test_no_secrets_in_ordinary_text(self):
        assert s._extract_secrets("nothing sensitive in this sentence") == {}


# ---------------------------------------------------------------------------
# JWT — structural validation of the header
# ---------------------------------------------------------------------------

class TestJWT:
    @staticmethod
    def _make_jwt(header: dict) -> str:
        hdr = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
        return f"{hdr}.{'a' * 20}.{'b' * 30}"

    def test_valid_jwt_detected(self):
        jwt = self._make_jwt({"alg": "HS256", "typ": "JWT"})
        assert s._looks_like_jwt(jwt)
        assert s._extract_secrets(f"auth {jwt} end")["jwt_tokens"] == {jwt}

    def test_header_without_alg_rejected(self):
        jwt = self._make_jwt({"typ": "JWT"})  # no "alg"
        assert not s._looks_like_jwt(jwt)

    def test_non_json_header_rejected(self):
        # eyJ-prefixed but header does not decode to JSON
        fake = "eyJnotbase64json.aaaaaaaaaa.bbbbbbbbbb"
        assert not s._looks_like_jwt(fake)


# ---------------------------------------------------------------------------
# Cryptocurrency addresses
# ---------------------------------------------------------------------------

class TestCryptoAddresses:
    def test_btc_genesis_address(self):
        genesis = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
        assert s._btc_base58check_ok(genesis)
        assert genesis in s._extract_btc(f"donate {genesis} please")

    def test_btc_bad_checksum_rejected(self):
        assert not s._btc_base58check_ok("1A1zP1eP5QGefi2DMPTfTL5SLmv7Divfaa")

    def test_btc_bech32_matched_structurally(self):
        bech = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
        assert bech in s._extract_btc(f"pay {bech} now")

    def test_eth_eip55_checksum(self):
        # Canonical EIP-55 example address
        good = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"
        assert s._eth_eip55_ok(good)
        assert good in s._extract_eth(f"wallet {good} here")

    def test_eth_mixed_case_bad_checksum_rejected(self):
        # Flip one letter's case -> EIP-55 checksum fails
        bad = "0x5AAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"
        assert not s._eth_eip55_ok(bad)

    def test_eth_all_lowercase_accepted_structurally(self):
        # No checksum applied when all-lower or all-upper
        assert s._eth_eip55_ok("0x" + "a" * 40)
