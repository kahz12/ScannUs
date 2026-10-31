"""
Precision of the identifier extractors on text that merely looks like PII,
and recall on real formats, so stricter rules do not lose true matches.

The extractors are called directly, because the checks here are about each
format and Presidio is too slow to run thousands of times.
"""

import random
import sys
import types
from types import SimpleNamespace

import pytest

from search import smart_search as s
from search.smart_search import (
    build_evidence,
    category_confidence,
    flatten_extracted,
)


SAMPLES = 800


def digits(count):
    return "".join(random.choice("0123456789") for _ in range(count))


def us_phone():
    return f"+1{random.randint(201, 989)}{random.randint(200, 999)}{random.randint(1000, 9999)}"


def version():
    return ".".join(str(random.randint(1, 200)) for _ in range(4))


@pytest.fixture(autouse=True)
def _repeatable_numbers():
    random.seed(1234)


@pytest.mark.parametrize("extractor, make_text", [
    (s._extract_cuit, lambda: f"call {us_phone()}"),
    (s._extract_cuit, lambda: f"Order no. {digits(11)} shipped"),
    (s._extract_phones_from_text, lambda: f"Invoice ref {digits(9)} paid"),
    (s._extract_phones_from_text, lambda: f"Order no. {digits(11)} shipped"),
    (s._extract_credit_cards, lambda: f"ts={random.randint(1600000000000, 1800000000000)}"),
    (s._extract_credit_cards, lambda: f"Tracking {digits(16)}"),
    (s._extract_credit_cards, lambda: f"Reference {digits(19)} issued"),
    (s._extract_ipv4, lambda: f"version {version()}"),
    (s._extract_ipv4, lambda: f"Mozilla/5.0 Chrome/{version()} Safari/537.36"),
    (s._extract_ipv4, lambda: f"firmware: {version()}"),
])
def test_lookalike_numbers_are_not_reported(extractor, make_text):
    assert [text for text in (make_text() for _ in range(SAMPLES)) if extractor(text)] == []


class TestRealValuesAreStillFound:
    @pytest.mark.parametrize("text", [
        "call +1 415 555 2671 now",
        "whatsapp +14155552671",
        "Tel: (415) 555-2671",
        "phone 4155552671",
        "teléfono 912 34 56 78",
        "+34 912 34 56 78",
    ])
    def test_phones(self, text):
        assert s._extract_phones_from_text(text)

    @pytest.mark.parametrize("text, expected", [
        ("4111 1111 1111 1111", "4111111111111111"),
        ("4111-1111-1111-1111", "4111111111111111"),
        ("Visa 4111111111111111", "4111111111111111"),
        ("4111111111111111|12/27|123", "4111111111111111"),
        ("tarjeta 5555555555554444", "5555555555554444"),
        ("amex 378282246310005", "378282246310005"),
        ("3782 822463 10005", "378282246310005"),
    ])
    def test_cards(self, text, expected):
        assert s._extract_credit_cards(text) == {expected}

    @pytest.mark.parametrize("text", [
        "20-12345678-6",
        "20 12345678 6",
        "CUIT 20123456786",
        "cuil: 20123456786",
    ])
    def test_cuit(self, text):
        assert s._extract_cuit(text) == {"20-12345678-6"}

    @pytest.mark.parametrize("text", [
        "server 8.8.8.8",
        "connect to 8.8.8.8.",
        "host=8.8.8.8:443",
    ])
    def test_ipv4(self, text):
        assert s._extract_ipv4(text) == {"8.8.8.8"}


class TestCardBrands:
    @pytest.mark.parametrize("number", [
        "4111111111111111", "5555555555554444", "2223003122003222", "378282246310005",
        "6011111111111117", "30569309025904", "3530111333300000", "6200000000000005",
    ])
    def test_known_test_numbers_are_accepted(self, number):
        assert s._card_brand_ok(number)
        assert s._luhn_ok(number)

    @pytest.mark.parametrize("number", [
        "1234567812345670",   # no issuer starts with 1
        "4111111111111",      # 13-digit Visa cards are no longer issued
        "37828224631000",     # American Express numbers have 15 digits
    ])
    def test_impossible_numbers_are_rejected(self, number):
        assert not s._card_brand_ok(number)


class TestCuitPrefixes:
    def test_unknown_prefix_is_rejected_even_with_a_valid_check_digit(self):
        assert s._extract_cuit("14-15555267-1") == set()

    def test_international_phone_prefix_rules_a_match_out(self):
        assert s._extract_cuit("+20-12345678-6") == set()


class TestEmails:
    @pytest.mark.parametrize("name", ["logo@2x.png", "hero@3x.webp", "app@1.2.js"])
    def test_asset_file_names_are_not_addresses(self, name):
        assert s._extract_emails_from_text(f"src={name}") == set()

    def test_real_address_survives(self):
        assert s._extract_emails_from_text("alice@acme-corp.io") == {"alice@acme-corp.io"}


class TestUsernames:
    @pytest.mark.parametrize("text", [
        "the user agent string",
        "login to continue",
        "each user has access",
        "username: password",
        "user=null",
    ])
    def test_prose_and_placeholders_are_not_usernames(self, text):
        assert "usernames" not in s.extract_information(text)

    @pytest.mark.parametrize("text, expected", [
        ("username: mgonzalez88.", "mgonzalez88"),
        ("login=jdoe", "jdoe"),
        ('user: "ana_lopez"', "ana_lopez"),
        ("usuario: pedro.gil", "pedro.gil"),
    ])
    def test_real_usernames_are_kept_without_trailing_punctuation(self, text, expected):
        assert s.extract_information(text)["usernames"] == [expected]


class TestPresidioFilter:
    TEXT = "Maria Gonzalez met Reach in Buenos Aires, ref 14155552671"

    def entity(self, kind, value):
        start = self.TEXT.index(value)
        return SimpleNamespace(entity_type=kind, start=start, end=start + len(value))

    def test_only_people_with_two_words_and_places_are_kept(self, monkeypatch):
        results = [
            self.entity("PERSON", "Maria Gonzalez"),
            self.entity("PERSON", "Reach"),
            self.entity("LOCATION", "Buenos Aires"),
            self.entity("US_BANK_NUMBER", "14155552671"),
            self.entity("US_DRIVER_LICENSE", "14155552671"),
        ]
        module = types.ModuleType("presidio_analyzer")
        module.AnalyzerEngine = lambda: SimpleNamespace(analyze=lambda text, language: results)
        monkeypatch.setitem(sys.modules, "presidio_analyzer", module)
        s._get_presidio.cache_clear()
        try:
            found = s._extract_presidio_entities(self.TEXT)
        finally:
            s._get_presidio.cache_clear()

        assert found == {"LOCATION": ["Buenos Aires"], "PERSON": ["Maria Gonzalez"]}


class TestConfidence:
    @pytest.mark.parametrize("category, level", [
        ("ibans", "high"),
        ("credit_cards", "high"),
        ("aws_access_keys", "high"),
        ("emails", "high"),
        ("phones", "medium"),
        ("ipv4", "medium"),
        ("usernames", "medium"),
        ("presidio_person", "low"),
    ])
    def test_levels(self, category, level):
        assert category_confidence(category) == level


class TestEvidenceRecords:
    DATA = {"emails": ["a@acme-corp.io"], "presidio": {"PERSON": ["Ana Gil"]}}

    def test_each_value_keeps_its_origin(self):
        records = build_evidence(self.DATA, "page text", "https://site.test/a", "deep-search")

        assert [(r["category"], r["value"], r["confidence"]) for r in records] == [
            ("emails", "a@acme-corp.io", "high"),
            ("presidio_person", "Ana Gil", "low"),
        ]
        for record in records:
            assert record["source"] == "https://site.test/a"
            assert record["tool"] == "deep-search"
            assert record["found_at"].endswith("+00:00")

    def test_hash_identifies_the_content(self):
        first = build_evidence(self.DATA, "page text", "u", "t")[0]["content_sha256"]
        same = build_evidence(self.DATA, "page text", "u", "t")[0]["content_sha256"]
        other = build_evidence(self.DATA, "changed text", "u", "t")[0]["content_sha256"]

        assert first == same != other
        assert len(first) == 64

    def test_flatten_groups_values_by_category(self):
        assert flatten_extracted(self.DATA) == {
            "emails": ["a@acme-corp.io"],
            "presidio_person": ["Ana Gil"],
        }
