"""
Unit tests for the PII / identifier extractors in ``search.smart_search``.

These functions are pure (no network, no filesystem), which makes them the
highest-value place to lock in behaviour. Expected values below use canonical
real-world test vectors wherever a checksum is involved (e.g. the well-known
``GB82WEST...`` IBAN, the Visa ``4111...`` Luhn card, the Bitcoin genesis
address) so the tests document *correct* behaviour rather than merely the
current implementation.
"""

import pytest

from search import smart_search as s


# ---------------------------------------------------------------------------
# Emails
# ---------------------------------------------------------------------------

class TestEmails:
    def test_plain_address_with_long_tld(self):
        assert s._extract_emails_from_text("write me: alice@corp.co.uk please") == {
            "alice@corp.co.uk"
        }

    def test_lowercased_and_deduped(self):
        got = s._extract_emails_from_text("A@Corp.com and a@corp.com")
        assert got == {"a@corp.com"}

    def test_obfuscation_at_dot_words(self):
        # "bob at corp dot io" -> bob@corp.io
        assert s._extract_emails_from_text("reach me at bob at corp dot io today") == {
            "bob@corp.io"
        }

    def test_obfuscation_bracketed(self):
        assert s._extract_emails_from_text("carol [at] mail-server [dot] net") == {
            "carol@mail-server.net"
        }

    def test_html_entity_obfuscation(self):
        # &#64; -> @, &#46; -> .
        assert s._extract_emails_from_text("dan&#64;acme&#46;dev") == {"dan@acme.dev"}

    def test_false_positive_domain_filtered(self):
        assert s._extract_emails_from_text("noise foo@example.com bar") == set()

    def test_bot_local_part_filtered(self):
        assert s._extract_emails_from_text("noreply@github.com") == set()
        assert s._extract_emails_from_text("postmaster@realdomain.org") == set()

    def test_mailto_href_extraction(self):
        html = '<a href="mailto:dev@startup.tech">contact</a>'
        assert s._extract_emails_from_html(html) == {"dev@startup.tech"}


# ---------------------------------------------------------------------------
# Phone numbers (libphonenumber-backed)
# ---------------------------------------------------------------------------

class TestPhones:
    def test_international_number(self):
        assert s._extract_phones_from_text("call +1 415 555 2671 now") == {
            "+1 415 555 2671"
        }

    def test_invalid_number_ignored(self):
        # 123 is not a valid number in any tried region
        assert s._extract_phones_from_text("ext 123 only") == set()

    def test_tel_href_extraction(self):
        html = '<a href="tel:+14155552671">call</a>'
        assert s._extract_phones_from_html(html) == {"+14155552671"}


# ---------------------------------------------------------------------------
# IBAN (ISO 13616 length + mod-97)
# ---------------------------------------------------------------------------

class TestIBAN:
    def test_canonical_valid_ibans(self):
        assert s._iban_is_valid("GB82 WEST 1234 5698 7654 32")
        assert s._iban_is_valid("DE89 3704 0044 0532 0130 00")

    def test_bad_checksum_rejected(self):
        assert not s._iban_is_valid("GB82 WEST 1234 5698 7654 33")

    def test_wrong_length_for_country_rejected(self):
        # GB IBANs are 22 chars; drop one to break the length check
        assert not s._iban_is_valid("GB82 WEST 1234 5698 7654 3")

    def test_extract_normalises_spacing(self):
        assert s._extract_ibans("acct GB82 WEST 1234 5698 7654 32 end") == {
            "GB82WEST12345698765432"
        }


# ---------------------------------------------------------------------------
# Credit cards (Luhn)
# ---------------------------------------------------------------------------

class TestCreditCards:
    def test_valid_visa_extracted_digits_only(self):
        assert s._extract_credit_cards("card 4111 1111 1111 1111 end") == {
            "4111111111111111"
        }

    def test_luhn_failure_rejected(self):
        assert s._extract_credit_cards("card 4111 1111 1111 1112 end") == set()

    def test_luhn_helper(self):
        assert s._luhn_ok("4111111111111111")
        assert not s._luhn_ok("4111111111111112")


# ---------------------------------------------------------------------------
# National identifiers
# ---------------------------------------------------------------------------

class TestNationalIdentifiers:
    def test_cuit_valid_and_invalid(self):
        assert s._cuit_is_valid("20123456786")
        assert not s._cuit_is_valid("20123456780")  # wrong check digit

    def test_cuit_extract_formats_with_dashes(self):
        assert s._extract_cuit("CUIT 20-12345678-6 registered") == {"20-12345678-6"}

    def test_dni_es_check_letter(self):
        assert s._dni_es_is_valid("12345678Z")
        assert not s._dni_es_is_valid("12345678A")  # wrong letter

    def test_ssn_valid_and_reserved_ranges(self):
        assert s._extract_ssn("ssn 219-09-9999 x") == {"219-09-9999"}
        # 666, 000, and 9xx areas are reserved / invalid
        assert s._extract_ssn("666-12-3456") == set()
        assert s._extract_ssn("000-12-3456") == set()
        assert s._extract_ssn("900-12-3456") == set()
        # group "00" and serial "0000" are invalid
        assert s._extract_ssn("219-00-1234") == set()
        assert s._extract_ssn("219-09-0000") == set()

    def test_cpf_valid_and_repeated_digits(self):
        assert s._cpf_is_valid("12345678909")
        assert not s._cpf_is_valid("11111111111")  # all-same is rejected

    def test_sin_luhn_validated(self):
        assert s._extract_sin("sin 046-454-286 ok") == {"046-454-286"}
        assert s._extract_sin("sin 046-454-287 ok") == set()

    def test_rfc_month_range_enforced(self):
        assert s._extract_rfc("rfc MELM850101HDF here") == {"MELM850101HDF"}
        # month 15 is impossible -> rejected
        assert s._extract_rfc("rfc MELM851501HDF here") == set()


class TestColombianIdentifiers:
    @pytest.mark.parametrize("text, expected", [
        ("identificado con TI 1012345678 quien", "TI 1012345678"),
        ("T.I. 99052312345", "TI 99052312345"),
        ("Tarjeta de identidad: 1001234567", "TI 1001234567"),
        ("C.C. No. 79.123.456 de Bogotá", "CC 79123456"),
        ("c.c. 52,345,678", "CC 52345678"),
        ("cédula de ciudadanía número 1.012.345.678", "CC 1012345678"),
        ("cedula 80123456", "CC 80123456"),
        ("cédula de extranjería 654321", "CE 654321"),
        ("CE N° 1234567", "CE 1234567"),
    ])
    def test_labelled_documents(self, text, expected):
        assert s._extract_col_id(text) == {expected}

    @pytest.mark.parametrize("text", [
        "para ti 123456789",      # "ti" is a common Spanish word
        "TI-84 Plus",
        "CC BY 4.0",
        "llama al 3001234567",    # a number without a document label
        "TI 12345",               # too short for any document
    ])
    def test_unlabelled_or_short_numbers_are_ignored(self, text):
        assert s._extract_col_id(text) == set()

    @pytest.mark.parametrize("nit, check_digit", [
        ("890903938", 8),   # Bancolombia
        ("899999068", 1),   # Ecopetrol
        ("800197268", 4),   # DIAN
    ])
    def test_nit_check_digit_of_known_companies(self, nit, check_digit):
        assert s._nit_check_digit(nit) == check_digit

    def test_nit_with_and_without_check_digit(self):
        assert s._extract_nit("NIT 890.903.938-8") == {"890903938-8"}
        assert s._extract_nit("NIT No. 900123456") == {"900123456"}

    def test_nit_with_a_wrong_check_digit_is_rejected(self):
        assert s._extract_nit("NIT 800197268-5") == set()

    def test_extract_information_reports_both_categories(self):
        out = s.extract_information("Cliente C.C. 79.123.456, empresa NIT 890903938-8")

        assert out["col_id"] == ["CC 79123456"]
        assert out["nit"] == ["890903938-8"]
        assert s.category_confidence("col_id") == "medium"


# ---------------------------------------------------------------------------
# Network identifiers
# ---------------------------------------------------------------------------

class TestNetworkIdentifiers:
    def test_ipv4_public_only(self):
        got = s._extract_ipv4("edge 8.8.8.8, lan 192.168.1.1, lo 127.0.0.1")
        assert got == {"8.8.8.8"}

    def test_ipv6_link_local_filtered(self):
        # A public v6 address is kept; fe80:: link-local is dropped
        got = s._extract_ipv6("a 2001:4860:4860::8888 b fe80::1 c")
        assert "2001:4860:4860::8888" in got
        assert "fe80::1" not in got

    def test_mac_normalised(self):
        assert s._extract_mac("dev 00:1A:2B:3C:4D:5E and AA-BB-CC-DD-EE-FF") == {
            "00:1a:2b:3c:4d:5e",
            "aa:bb:cc:dd:ee:ff",
        }


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------

class TestExtractInformation:
    def test_empty_text_returns_empty_dict(self):
        assert s.extract_information("") == {}
        assert s.extract_information(None) == {}

    def test_absent_categories_are_omitted(self):
        # Plain prose with no identifiers should not invent keys
        assert s.extract_information("just some ordinary words here") == {}

    def test_multiple_categories_detected(self):
        blob = (
            "Contact alice@corp.co.uk or call +1 415 555 2671. "
            "Card 4111 1111 1111 1111. Server 8.8.8.8."
        )
        out = s.extract_information(blob)
        assert out["emails"] == ["alice@corp.co.uk"]
        assert out["phones"] == ["+1 415 555 2671"]
        assert out["credit_cards"] == ["4111111111111111"]
        assert out["ipv4"] == ["8.8.8.8"]

    def test_values_are_sorted_lists(self):
        out = s.extract_information("ips 9.9.9.9 and 1.1.1.1")
        assert out["ipv4"] == ["1.1.1.1", "9.9.9.9"]  # sorted, list not set
        assert isinstance(out["ipv4"], list)
