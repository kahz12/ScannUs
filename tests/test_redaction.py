"""Sensitive values replaced before text goes to an AI provider."""

from search.smart_search import redact_for_model, redact_sensitive


def test_colombian_document_keeps_its_label():
    assert redact_sensitive("identificado con TI 1012345678 quien") == (
        "identificado con TI [withheld: col_id] quien"
    )


def test_grouped_numbers_are_withheld_as_written():
    text = "C.C. No. 79.123.456 de Bogotá, NIT 890.903.938-8"

    assert redact_sensitive(text) == (
        "C.C. No. [withheld: col_id] de Bogotá, NIT [withheld: nit]"
    )


def test_card_and_iban_with_spaces():
    text = "tarjeta 4111 1111 1111 1111 y cuenta GB82 WEST 1234 5698 7654 32"

    assert redact_sensitive(text) == (
        "tarjeta [withheld: credit_cards] y cuenta [withheld: ibans]"
    )


def test_other_national_ids():
    assert redact_sensitive("CUIT 20-12345678-6") == "CUIT [withheld: cuit]"
    assert redact_sensitive("ssn 219-09-9999") == "ssn [withheld: ssn]"


def test_secrets_and_whole_private_keys():
    text = ("key AKIAIOSFODNN7EXAMPLE\n-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n"
            "-----END RSA PRIVATE KEY-----\nafter")

    assert redact_sensitive(text) == (
        "key [withheld: aws_access_keys]\n[withheld: private_keys]\nafter"
    )


def test_private_key_without_its_end_line_is_withheld_to_the_end():
    assert redact_sensitive("x -----BEGIN PRIVATE KEY-----\nMIIEow") == (
        "x [withheld: private_keys]"
    )


def test_pivots_stay_readable():
    text = ("Ana Ruiz, hello@lumenforge.example, +1 415 555 2671, "
            "https://docs.example/document/48213, 8.8.8.8")

    assert redact_sensitive(text) == text


def test_a_longer_number_that_contains_the_value_is_left_alone():
    assert redact_sensitive("TI 1012345678 y pedido 91012345678") == (
        "TI [withheld: col_id] y pedido 91012345678"
    )


def test_empty_text():
    assert redact_sensitive("") == ""


def test_nested_results_are_withheld_and_other_values_kept():
    result = {
        "status": "ok",
        "summary": "1 hit",
        "data": {"count": 1, "ok": True, "results": [
            {"title": "Ficha", "description": "con TI 1012345678"},
        ], "pair": ("CC 79123456", None)},
    }

    assert redact_for_model(result) == {
        "status": "ok",
        "summary": "1 hit",
        "data": {"count": 1, "ok": True, "results": [
            {"title": "Ficha", "description": "con TI [withheld: col_id]"},
        ], "pair": ("CC [withheld: col_id]", None)},
    }
